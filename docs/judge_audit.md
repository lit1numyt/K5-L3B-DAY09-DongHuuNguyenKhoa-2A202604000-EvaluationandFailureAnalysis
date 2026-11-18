# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 10` (FAIL là lớp dương: việc của judge là tìm lỗi).

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Fail rate quan sát → Rogan-Gladen | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | 0.28 → 0.30 | **PASS** | **dùng** (chỉ cho giọng điệu, không gate tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | 0.09 → 0.30 | **FAIL** (κ, R) | **loại** |

## ≥5 case audit thủ công

Tone (cả 10 bất đồng):

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em"/"nha" quá suồng sã. Rubric: liệt kê đại từ được phép (LogiX/anh/chị), cấm "em… nha", "bạn ơi". |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Cùng lỗi xưng hô ("bạn"). Gộp vào luật đại từ ở #1, thêm ví dụ few-shot FAIL. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge bị đánh lừa bởi "Dạ, vui lòng". Rubric: câu mệnh lệnh/gạt khách ("không cần nhắn thêm") = FAIL dù có từ lịch sự. |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu xin lỗi. Rubric: xin lỗi **không bắt buộc**; ngắn, đủ ý, lễ phép là PASS. |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Style guide CS LogiX cho phép "refund". Rubric: whitelist thuật ngữ tiếng Anh được phép. |
| 6 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống — thực ra là lỗi **nội dung** (FM-08), không phải giọng. Không sửa rubric tone; chuyển sang grader code `reply_matches_ledger`/kiểm cam kết. |
| 7 | H-070 "…đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Rubric: emoji trong ngữ cảnh khiếu nại = FAIL. |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Ghi chú người chấm: nhãn người sai (đọc nhầm ticket). **Sửa nhãn** thành FAIL ở bản CSV kế tiếp (v2, có version), không sửa trong bản đang dùng để calibrate. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | Người (chấp nhận được) | Lỗi gõ nhỏ. Rubric: lặp từ đơn lẻ không làm FAIL tone. |
| 10 | H-094 "Da, LogiX da hoan 40.000đ…" (mất dấu) | PASS | FAIL | Người | Rubric: tiếng Việt không dấu / dịch máy = FAIL. |

Helpful (mẫu từ 21 false negative):

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 11 | HL-015 "đã hoàn 55.000đ cho đơn O-112" (ledger 40.000) | PASS | FAIL (sai tiền) | Người | Judge không thấy ledger nên không thể biết số sai. |
| 12 | HL-016 xin lỗi dài 3 câu + "đã hoàn 55.000đ" (ledger 35.000) | PASS | FAIL (sai tiền) | Người | Câu xin lỗi dài làm judge chấm "hữu ích" → thiên vị độ dài/lịch sự. |
| 13 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL (sai xưng hô) | Người | Judge helpful cũng bỏ lỡ lỗi tone mà judge tone bắt được. |

## Kết luận

- **tone_ok: dùng được** — κ 0.757, P 0.857, R 0.80 đều trên sàn. Chỉ dùng như metric theo dõi về giọng điệu; không bao giờ gate tiền hay approval. Sửa rubric theo #1–#5, #7, #9, #10 rồi calibrate lại trên nhãn mới.
- **helpful: loại, không được dùng làm gate.** Ma trận: tp 9, fn 21 → recall 0.30 (bắt được 3/10 lỗi); κ 0.375 < 0.6. Precision 1.0 không cứu được: judge rất ít khi nói FAIL (9/100), nên khi nó nói PASS thì không có nghĩa gì. Nhìn theo loại lỗi người gắn: **18/18 lỗi "sai tiền" bị judge cho PASS**, 3/3 "sai xưng hô" cũng PASS; judge chỉ bắt được lỗi hiển nhiên trên mặt chữ (giọng cụt, lạc đề, không hỏi mã đơn — 9/9). Lỗi chính của tiêu chí helpful lại là tiền, mà judge không có ledger → về nguyên tắc không thể chấm. Rogan-Gladen kéo fail rate 0.09 lên 0.30, tức judge đang che 2/3 số lỗi. Nếu dùng làm gate, một PR làm sai tiền sẽ được merge.
- **Thay thế**: phần "sai tiền" của helpful chấm bằng code — `reply_matches_ledger` (FM-08, blocking) so số trong reply với ledger. Phần còn lại (lạc đề, không hỏi mã đơn) có thể tách thành tiêu chí judge riêng và calibrate lại.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng/tiêu chí); cần nhãn người mới làm held-out thật. Một nhãn người đã biết là sai (H-081) → nhãn người cũng cần kiểm chéo (2 người, đo κ giữa người).
