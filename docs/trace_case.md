# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

Output (rút gọn):
```
== seeded_regression C-014@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff            {... "task": "check_applicable_policy" ...}
   2 investigator       {"lookup_order": {"visible": true, ... "order_id": "O-515", "status": "delivered_late", ...
   3 quote              {"amount_vnd": 150000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03", "DMG-04"], ...
   4 refund_history     {"refund_count": 1, "refunded_vnd": 30000}
   5 proposal           {"amount_vnd": 120000}
   6 reply              {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
  refund_vnd     ledger=90000    label=120000   <-- differs
  status         result=resolved label=resolved

== fixed C-014@11  lab8 grader: PASS (ok)
   3 quote              {"amount_vnd": 150000, ...}
   4 reply              {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
  refund_vnd     ledger=120000   label=120000
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, run ID `E-seeded_regression-20261118-a66d` (item E-014, fail ở cả 5 seed) |
| Triệu chứng | `pass_rate` FAIL (`proposal_mismatch`), `refund_amount_correct` FAIL (ledger 90.000 ≠ nhãn 120.000), `reply_matches_ledger` FAIL (reply nói 120.000đ, ledger giữ 90.000đ), `quote_kept` FAIL. Status vẫn `resolved` — nhìn reply thì tưởng đúng vì 120.000 trùng nhãn. |
| Bước sai đầu tiên | **Event 5 `proposal` `{"amount_vnd": 120000}`**: agent tự trừ 30.000 đã hoàn trước khi gọi host. |
| Vì sao là bước *đầu tiên* | Event 2 đọc đúng đơn O-515 (verified damage, trễ 5 ngày). Event 3 `quote` 150.000 đúng chính sách (max(30.000, 150.000), trần DMG-04). Event 4 `refund_history` đọc đúng 30.000 đã hoàn (lệnh read-only, chưa sai). Sai bắt đầu khi event 5 dùng số đó để trừ: host `lab8.durability.issue_refund` **cũng** trừ phần đã hoàn theo trần đơn → 120.000 − 30.000 = 90.000 được ghi. |
| Failure mode | **FM-05 pre_deducted** (kèm hệ quả FM-08: reply báo số mình tự tính, không phải số host ghi) |
| Đối chứng | `fixed` C-014@11: không có event `refund_history` / `proposal`; quote 150.000 được truyền thẳng cho host, host trừ 30.000 → ledger 120.000 = nhãn; reply nói 120.000đ = ledger. |
| Regression test | `tests/test_lab9_trace_case.py::test_trace_case_c014_seed11_first_wrong_step` (marker `student`, chạy trong CI): khẳng định event thứ 5 là `proposal 120000`, ledger 90.000, và `refund_amount_correct`, `quote_kept`, `reply_matches_ledger` đều FAIL trên `seeded_regression`; trên `fixed` không có `proposal` và mọi grader PASS. Đã thấy fail trên variant lỗi và pass trên `fixed`. Item E-014 đã có sẵn trong eval set v1 nên không thêm item mới. |
| Chưa chắc chắn | Trace không ghi lý do agent trừ (không có event "reasoning"); từ trace chỉ suy ra được *rằng* proposal = quote − refunded_vnd. Trace cũng không ghi event của host (số host đã trừ) — số 90.000 suy ra từ ledger, không từ trace. Với LLM thật, lỗi này có thể chỉ xuất hiện ở một phần seed. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai. (Ở case này reply nói 120.000đ — đúng bằng nhãn — trong khi ledger chỉ có 90.000.)
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
