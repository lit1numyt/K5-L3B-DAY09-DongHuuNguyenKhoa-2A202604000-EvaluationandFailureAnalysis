"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for name, rep in (("PR", pr), ("baseline", base)):
        problems += [f"{name} {p}" for p in _report_problems(rep, graded, spec)]
    if problems:
        return problems
    # Same experiment on both sides: same seeds, same item count, same (item, seed) cells.
    pm, bm = pr.get("manifest", {}), base.get("manifest", {})
    if sorted(pm.get("seeds") or []) != sorted(bm.get("seeds") or []):
        problems.append(f"seeds {pm.get('seeds')} differ from the baseline's {bm.get('seeds')} (cherry-picked seeds?)")
    if pm.get("items") != bm.get("items"):
        problems.append(f"manifest items {pm.get('items')} != baseline {bm.get('items')}")
    pr_cols = set((pr.get("rows") or [{}])[0])
    for mid in graded:
        if mid in (base.get("rows") or [{}])[0] and mid not in pr_cols:
            problems.append(f"graded metric {mid} is in the baseline rows but missing from every PR row (grader dropped?)")
    pc, bc = _cells(pr), _cells(base)
    if pc != bc:
        miss, extra = sorted(bc - pc), sorted(pc - bc)
        problems.append(f"(item, seed) set differs from the baseline: {len(miss)} missing {miss[:3]}, "
                        f"{len(extra)} extra {extra[:3]}")
    # Slice tags come from the label; relabelling an item out of a slice hides it from the slice gate.
    ps, bs = _item_slices(pr), _item_slices(base)
    relabelled = sorted(i for i in ps.keys() & bs.keys() if ps[i] != bs[i])
    if relabelled:
        i = relabelled[0]
        problems.append(f"slice tags changed on {len(relabelled)} item(s), e.g. {i}: {sorted(bs[i])} -> {sorted(ps[i])}")
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _is_bad_number(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _walk_numbers(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_numbers(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk_numbers(v, f"{path}[{i}]")
    else:
        yield path, obj


def _cells(rep: dict) -> set[tuple[str, int]]:
    return {(r.get("item_id"), r.get("seed")) for r in rep.get("rows") or []}


def _item_slices(rep: dict) -> dict[str, frozenset]:
    out: dict[str, set] = {}
    for r in rep.get("rows") or []:
        out.setdefault(r.get("item_id"), set()).add(frozenset(r.get("slices") or []))
    # an item whose rows disagree on their own tags is itself suspicious: keep the union marker
    return {i: (next(iter(v)) if len(v) == 1 else frozenset({"<inconsistent>"})) for i, v in out.items()}


def _report_problems(rep: dict, graded: list[str], spec: dict) -> list[str]:
    """Checks one report can fail on its own, before it is compared with anything."""
    problems: list[str] = []
    bad = [p for p, v in _walk_numbers(rep.get("metrics") or {}) if _is_bad_number(v)]
    problems += [f"metric {p} is NaN/inf" for p in bad]
    rows = rep.get("rows") or []
    if not rows:
        return problems + ["has no rows"]
    bad_cells = [f"row {r.get('item_id')}@{r.get('seed')}.{k}" for r in rows for k, v in r.items() if _is_bad_number(v)]
    problems += [f"{c} is NaN/inf" for c in bad_cells[:3]]
    m = rep.get("manifest") or {}
    want = (m.get("items") or 0) * len(m.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {m.get('items')} items x {len(m.get('seeds') or [])} seeds = {want}")
    cells = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({c for c in cells if cells.count(c) > 1})
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), e.g. {dups[0]}")
    seeds = set(m.get("seeds") or [])
    off = sorted({r.get("seed") for r in rows} - seeds)
    if off:
        problems.append(f"rows with seeds {off} not in the manifest")
    if len({r.get("item_id") for r in rows}) != m.get("items"):
        problems.append(f"{len({r.get('item_id') for r in rows})} distinct items, manifest says {m.get('items')}")
    if rep.get("evaluator_failures"):
        problems.append(f"{len(rep['evaluator_failures'])} evaluator failure(s), first: {rep['evaluator_failures'][0]}")
    for mid in graded:
        if mid not in rows[0] and mid not in (rep.get("metrics") or {}):
            continue                      # metric not graded in this report at all: the gate reports it MISSING
        missing = [r for r in rows if r.get(mid) is None]
        if missing:
            problems.append(f"{len(missing)} row(s) have no value for graded metric {mid} "
                            f"(e.g. {missing[0].get('item_id')}@{missing[0].get('seed')}): crashed grader?")
    # The headline numbers must be what the rows say: catches a hand-edited `metrics` block.
    kinds = {x["id"]: x.get("kind") for x in spec.get("metrics", [])}
    reported = rep.get("metrics") or {}
    for mid in graded:
        vals = [r.get(mid) for r in rows if r.get(mid) is not None]
        if mid not in reported or not vals or len(vals) != len(rows):
            continue
        want_v = sum(vals) if kinds.get(mid) == "safety" else round(sum(vals) / len(vals), 4)
        got_v = reported[mid]
        if not isinstance(got_v, (int, float)) or abs(float(got_v) - float(want_v)) > 1e-3:
            problems.append(f"metric {mid} reported {got_v} but rows give {want_v}")
    if "pass_rate" in rows[0] and isinstance(reported.get("pass_5"), (int, float)):
        by_item: dict[str, list] = {}
        for r in rows:
            by_item.setdefault(r.get("item_id"), []).append(bool(r.get("pass_rate")))
        want_p5 = round(sum(all(v) for v in by_item.values()) / len(by_item), 4)
        if abs(reported["pass_5"] - want_p5) > 1e-3:
            problems.append(f"metric pass_5 reported {reported['pass_5']} but rows give {want_p5}")
    if "pass_rate" in rows[0]:
        by_item = {}
        for r in rows:
            by_item.setdefault(r.get("item_id"), []).append(bool(r.get("pass_rate")))
        for key, v in reported.items():
            if not (key.startswith("pass_at_") or key.startswith("pass_hat_")) or not isinstance(v, (int, float)):
                continue
            k = int(key.rsplit("_", 1)[1])
            fn = stats.pass_at_k if key.startswith("pass_at_") else stats.pass_hat_k
            try:
                want_k = round(sum(fn(len(x), sum(x), k) for x in by_item.values()) / len(by_item), 4)
            except ValueError:
                problems.append(f"metric {key} reported {v} but items have fewer than {k} runs")
                continue
            if abs(v - want_k) > 1e-3:
                problems.append(f"metric {key} reported {v} but rows give {want_k}")
    return problems


def _loosened(name: str, th: dict, base_th: dict) -> list[str]:
    out = []
    if "max" in base_th and ("max" not in th or th["max"] > base_th["max"]):
        out.append(f"{name}: max {base_th['max']} -> {th.get('max', 'removed')}")
    if "min" in base_th and ("min" not in th or th["min"] < base_th["min"]):
        out.append(f"{name}: min {base_th['min']} -> {th.get('min', 'removed')}")
    if "max_increase" in base_th and ("max_increase" not in th or th["max_increase"] > base_th["max_increase"]):
        out.append(f"{name}: max_increase {base_th['max_increase']} -> {th.get('max_increase', 'removed')}")
    if base_th.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append(f"{name}: no_significant_drop dropped")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => every threshold may only get stricter. Anything else needs a new version."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                         # new eval-set version: thresholds start over (documented in PRD)
    problems: list[str] = []
    for key in ("eval_set", "labels", "adversarial_pack"):
        if spec.get(key) != base_spec.get(key):
            problems.append(f"RATCHET {key} changed ({base_spec.get(key)} -> {spec.get(key)}) on the same eval-set version")
    if sorted(spec.get("seeds") or []) != sorted(base_spec.get("seeds") or []):
        problems.append(f"RATCHET seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if (sb.get("confidence", 0.95) > bb.get("confidence", 0.95) or sb.get("n_resamples", 1000) < bb.get("n_resamples", 1000)
            or sb.get("rng") != bb.get("rng") or sb.get("method") != bb.get("method")):
        problems.append(f"RATCHET bootstrap settings changed {bb} -> {sb}")
    if set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []):
        problems.append(f"RATCHET pass_k {base_spec.get('pass_k')} -> {spec.get('pass_k')}")
    now = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = now.get(bm["id"])
        if m is None:
            problems.append(f"RATCHET metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            problems.append(f"RATCHET metric {bm['id']} no longer blocking")
        problems += [f"RATCHET {x}" for x in _loosened(bm["id"], m.get("threshold") or {}, bm.get("threshold") or {})]
    now_sl = {(x.get("name"), x.get("metric")): x for x in spec.get("slices") or []}
    for bsl in base_spec.get("slices") or []:
        key = (bsl.get("name"), bsl.get("metric"))
        sl = now_sl.get(key)
        tag = f"slice {key[0]}/{key[1]}"
        if sl is None:
            problems.append(f"RATCHET {tag} removed")
            continue
        if bsl.get("blocking") and not sl.get("blocking"):
            problems.append(f"RATCHET {tag} no longer blocking")
        problems += [f"RATCHET {x}" for x in _loosened(tag, sl, bsl)]
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note = "ok", ""
        if not a:
            verdict, val = "missing", None          # a slice that vanished from the PR must not pass silently
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label} ({len(a)} items)")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
