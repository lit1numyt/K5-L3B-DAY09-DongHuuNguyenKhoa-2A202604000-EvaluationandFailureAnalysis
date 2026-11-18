"""M1/M3 regression tests: the FM-08 / quote graders on hand-built Trials, and the trace case in
docs/trace_case.md (seeded_regression C-014@11, FM-05 pre-deduction) replayed on real shapes."""
import pytest

pytestmark = pytest.mark.student
LABEL = {"status": "resolved", "refund_vnd": 120000, "approval_ok": True, "forbid_substrings": []}


@pytest.fixture(scope="module")
def graders():
    from lab9 import graders

    return graders


def ctx(trial, label=LABEL):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def trial(ledger=120000, status="resolved", reply=None, quote=None, proposal=None, stated=None):
    events = []
    if quote is not None:
        events.append({"kind": "quote", "payload": {"amount_vnd": quote}})
    if proposal is not None:
        events.append({"kind": "proposal", "payload": {"amount_vnd": proposal}})
    if reply is not None:
        events.append({"kind": "reply", "payload": {"text": reply}})
    return {"snapshot": {"refund_vnd": ledger, "refund_count": int(ledger > 0)}, "unexpected_rows": 0,
            "blob": "", "events": events, "result": {"status": status, "proposal_amount": stated},
            "lab8_pass": True, "lab8_reason": None}


@pytest.mark.parametrize("text,amounts", [
    ("Dạ, LogiX đã hoàn 120.000đ cho đơn O-515.", [120000]),
    ("LogiX đã hoàn phí 35.000đ cho đơn O-107 của anh/chị ạ.", [35000]),
    ("Refunded 35,000 VND for O-107", [35000]),
    ("Đã hoàn 20000 đồng", [20000]),
    ("Dạ, đơn O-202 chưa đủ điều kiện hoàn.", []),
])
def test_reply_amount_parser_ignores_order_ids(graders, text, amounts):
    assert graders.reply_amounts(text) == amounts


def test_reply_matches_ledger_ok(graders):
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(reply="Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."))).value is True


def test_reply_states_amount_ledger_does_not_hold(graders):
    # FM-08: the agent tells the customer 120.000đ, the ledger holds 90.000đ
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(ledger=90000, reply="Dạ, LogiX đã hoàn 120.000đ."))).value is False


def test_resolved_with_empty_ledger_is_misreport(graders):
    # FM-02 symptom seen by FM-08: host denied, agent says resolved; no reply event needed
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(ledger=0, status="resolved"))).value is False


def test_denied_with_refund_in_ledger_is_misreport(graders):
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(ledger=20000, status="denied"))).value is False


def test_quote_kept(graders):
    q = graders.QuoteKept()
    assert q.evaluate(ctx(trial(quote=150000, stated=150000))).value is True
    assert q.evaluate(ctx(trial(quote=150000, proposal=120000, stated=120000))).value is False   # pre-deducted
    assert q.evaluate(ctx(trial(quote=35000, stated=30000))).value is False                      # rounded, no event
    assert q.evaluate(ctx(trial(stated=0))).value is True                                        # no quote: vacuous


def test_trace_case_c014_seed11_first_wrong_step():
    """docs/trace_case.md: seeded_regression C-014@11. Event 5 (`proposal` 120000) is the first wrong
    step; the graders must catch it on seeded_regression and stay silent on fixed."""
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    def grade(shape):
        case = investigate(shape, "C-014", 11)
        c = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"], output=case["trial"],
                             duration=0.0, _span_tree=None, attributes={}, metrics={})
        return case["trial"], {m: g().evaluate(c).value for m, g in graders.GRADERS.items()}

    bad, v = grade("seeded_regression")
    kinds = [e["kind"] for e in bad["events"]]
    assert kinds.index("proposal") == 4 and bad["events"][4]["payload"]["amount_vnd"] == 120000
    assert bad["snapshot"]["refund_vnd"] == 90000
    assert v["refund_amount_correct"] is False and v["quote_kept"] is False and v["reply_matches_ledger"] is False

    good, v = grade("fixed")
    assert "proposal" not in [e["kind"] for e in good["events"]]
    assert good["snapshot"]["refund_vnd"] == 120000
    assert all(v[m] for m in ("pass_rate", "refund_amount_correct", "quote_kept", "reply_matches_ledger"))
