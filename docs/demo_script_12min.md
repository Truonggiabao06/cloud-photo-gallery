# Kịch bản demo 12 phút

TV 5 chuẩn bị hai revision Backend hợp lệ, một Worker revision tốt và failpoint đã xác nhận trên staging. Chạy một buổi rehearsal gồm Test 1–3, vòng load và crash drill đủ dài để nhận alert. Chuẩn bị sẵn raw JSON, logs đã lọc, manifest và ảnh incident. Khi trình bày, ghi rõ bằng chứng nào là buổi rehearsal và thao tác nào đang chạy live.

| Thời gian | Người nói và thao tác | Bằng chứng trên màn hình |
| --- | --- | --- |
| 00:00–01:15 | TV 5 mở sơ đồ thật. Chỉ entry points, Entra, GCS private, Pub/Sub OIDC, Worker IAM, đường DB và failure domain. Nói lý do chọn Entra trên GCP. | Sơ đồ trong báo cáo và URL staging |
| 01:15–02:45 | TV 1/2 đăng nhập owner, tạo album, upload JPEG, mở màn hình progress, rồi xem hai thumbnail. Đăng nhập invited viewer để kiểm tra quyền xem. | Trạng thái chuyển từ pending/processing sang complete, hai kích cỡ và truy cập theo role |
| 02:45–04:15 | TV 5 hiển thị Test 1 và Test 3 đã thu trong rehearsal. Trỏ manifest 100 + 5, hai tên object deterministic và API status của một tệp hỏng. Mở unsigned GCS URL đã bỏ query hoặc dòng JSON HTTPS 403, không trình chiếu URL signed. | 100 records/200 thumbnail và 5 FAILED có lý do; kiểm tra 401/403/404 |
| 04:15–05:30 | TV 3/5 hiển thị Test 2. Giải thích 5 Pub/Sub message IDs có cùng payload digest. Cho xem 5 ACK, 1 record, 1 successful terminal commit, 2 key giữ nguyên và ledger DB theo cùng business key. | Evidence Test 2, log và ledger đã lọc |
| 05:30–07:45 | TV 3/5 tạo một file drill theo runbook. Mở GCS/Logging thấy ảnh nhỏ đã ghi, job chưa hoàn tất và process exit. Chuyển 100% Worker traffic về revision tốt. Đợi cùng photoId chuyển thành complete. | Hai revision, log drill_exit, retry/ACK, đủ ảnh sau phục hồi |
| 07:45–09:00 | TV 5 mở Dashboard: giải thích đủ 5 chỉ số. Mở incident rehearsal, nêu ngưỡng 120 giây, retest 60 giây, độ trễ đo được, hành động đầu tiên và lý do DLQ chỉ là phương án sau. | Ảnh Dashboard, email/incident đã lọc và mốc thời gian |
| 09:00–10:15 | TV 5 mở GitHub workflow thành công; trỏ digest, revision. Demo backend rollback CLI về bản trước đã xác minh, chạy health sau đó restore bản hiện tại. | Run ID, đầu ra update-traffic, health |
| 10:15–11:15 | TV 5 đọc thông số load từ raw JSON, gồm dataset, warmup, duration, concurrency, RPS đạt được, error rate, p95 và số mẫu. Nếu có 429, chỉ đúng revision và báo cáo kết quả thật. | JSON `parameters` và `summary` |
| 11:15–12:00 | TV 5 nêu chi phí Singapore/730 giờ, khoản DB/NAT, budget alert và kế hoạch cleanup. Mở bằng chứng recreate/destroy từ rehearsal; giữ staging để chấm theo lịch. | Bảng chi phí và Terraform evidence |

Khi alert live cần thời gian hơn demo, dùng incident rehearsal tại mốc 07:45. Khi Worker recovery vượt thời lượng, giữ job ID và dùng capture rehearsal có cùng kịch bản để trình bày kết quả. Quay màn hình 12 phút ở độ phân giải đọc được terminal, ẩn token và alert email cá nhân khi chia sẻ. Cắt video sau khi xác nhận mọi đoạn bằng chứng đã lọc, lưu tên `project07-demo.mp4` và URL giảng viên truy cập được.

Lệnh xem summary trước khi quay:

```bash
jq '.checks | map_values({passed,failure})' "$RUN_JSON"
jq '.checks.test1 | {readyRecords,thumbnailCount}' "$RUN_JSON"
jq '.checks.test2 | {messageIds,acknowledgedReplayIds,terminalCommitLogCount}' "$RUN_JSON"
jq '.parameters,.summary' "$LOAD_JSON"
```
