# Giai đoạn 2 · Kiểm chứng Render và Supabase

Chạy hai ứng dụng trên máy với PostgreSQL và bucket riêng tư ở Supabase staging. Giữ môi trường Render/GCP hiện có tách riêng. Giai đoạn này chưa cần tài khoản Render.

## Chuẩn bị trong Supabase

| Biến cho Backend và Worker | Lấy giá trị ở đâu |
| --- | --- |
| `DATABASE_URL` | Bấm **Connect → Session pooler**. Dùng host, port 5432 và database trong chuỗi mẫu. Đặt mật khẩu URL-encoded và dùng tài khoản runtime có quyền `photo_runtime`. |
| `S3_ENDPOINT` | **Storage → Configuration → S3**. Bật S3 protocol và sao chép endpoint đầy đủ, gồm đường dẫn `/storage/v1/s3`. |
| `S3_REGION` | Sao chép region do chính màn hình S3 cung cấp. |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Tạo cặp khóa trong **Storage → Configuration → S3**. Giá trị secret chỉ dùng phía server. |
| `S3_BUCKET` | Tên bucket private bạn tạo ở **Storage → Buckets**. |

Trên **SQL Editor** của project staging, áp theo thứ tự `db/01_database_schema.sql`, `db/04_backend_integration.sql`, `db/05_runtime_permissions.sql`. Tạo một login dành cho ứng dụng, cấp role `photo_runtime`, rồi dùng thông tin đăng nhập runtime trong Session pooler URI. Các file SQL đã được dùng trong bản PostgreSQL hiện tại. Bucket chỉ dùng cho test tổng hợp. Tắt Data API nếu project chỉ truy cập bảng qua PostgreSQL.

Tải chứng chỉ CA từ **Database → Settings** và đặt SSL cho cả hai ứng dụng với `?sslmode=verify-full&sslrootcert=<đường dẫn CA đã URL-encode>`. Ví dụ đường dẫn Windows `C:/certs/prod-supabase.cer` có thể được ghi trong URI dưới dạng `C%3A%2Fcerts%2Fprod-supabase.cer`. Bật Enforce SSL cho project staging. [Hướng dẫn Session pooler và SSL](https://supabase.com/docs/guides/database/psql) · [Thông tin xác thực S3](https://supabase.com/docs/guides/storage/s3/authentication)

## Chạy hai dịch vụ từ repo

Tạo `backend/.env` và `worker/.env` từ các file ví dụ. Thêm năm cài đặt S3 ở bảng trên, `DATABASE_URL` và cùng một `WORKER_SHARED_SECRET` ngẫu nhiên ít nhất 32 ký tự vào cả hai file. Tạo secret mới cho mỗi môi trường và giữ nó ngoài Git.

- Backend dùng `STORAGE_BACKEND=s3`, `WORKER_WAKE_URL=http://127.0.0.1:8080` và `PORT=3000`. Đặt các biến Entra và CORS hiện có nếu muốn đăng nhập bằng Frontend.
- Worker dùng `WORKER_MODE=outbox` và `BACKEND_BASE_URL=http://127.0.0.1:3000`. Giữ `OUTBOX_POLL_SECONDS=20` cho lần thử đầu. Trên Render, Docker đọc mode này và lắng nghe `PORT`.
- Backend Ops dùng `OPS_METRICS_TOKEN` ngẫu nhiên riêng, tối thiểu 32 ký tự. Webhook là tùy chọn, xem mục cuối.

Mở ba cửa sổ PowerShell ở thư mục gốc repo. Chạy Backend ở cửa sổ 1.

```powershell
cd backend
npm.cmd ci
npm.cmd start
```

Chạy Worker ở cửa sổ 2. Flask CLI phù hợp cho local trên Windows. Docker dùng Gunicorn.

```powershell
cd worker
py -m pip install -r requirements.txt
py -m flask --app 'render_app:create_app()' run --host 127.0.0.1 --port 8080 --no-reload
```

Kiểm tra và chạy script ở cửa sổ 3.

```powershell
Invoke-RestMethod http://127.0.0.1:3000/health
Invoke-RestMethod http://127.0.0.1:8080/health
cd backend
$env:QA_CONFIRM_STAGING = 'yes'
node scripts/verify-supabase.cjs
Remove-Item Env:QA_CONFIRM_STAGING
```

Script tạo một album và ảnh thử, kiểm tra URL chưa ký bị từ chối, URL đã ký đọc được file, đưa cùng sự kiện trở lại Outbox và xác nhận chỉ có một job hoàn tất, một bản ghi dedup và đúng hai WebP có nội dung giữ nguyên. Script in photo ID để truy vết. Các bản ghi và ảnh tổng hợp được giữ trong staging làm bằng chứng. Khi chạy trên máy hoặc Render, chỉ chia sẻ kết quả cuối, giữ URL ký, chuỗi kết nối và các khóa trong môi trường riêng.

## Metrics và cảnh báo

`GET /api/metrics` dùng header `Authorization: Bearer <OPS_METRICS_TOKEN>`. JSON dùng làm endpoint Ops cho demo. Health chỉ trả trạng thái cơ bản. Trong metrics, p95, thời gian trung bình và tỷ lệ lỗi dùng cửa sổ một giờ, độ trễ tính trên ảnh hoàn thành. Retry là tổng `attempts` của Outbox. Dung lượng thumbnail lấy từ số byte được ghi vào kết quả hoàn tất trong PostgreSQL. `completedWithoutThumbnailSize` cho biết số ảnh cũ chưa có số liệu này.

Để gửi cảnh báo, đặt `OPS_ALERT_WEBHOOK_URL` và `OPS_ALERT_WEBHOOK_FORMAT` là `discord`, `slack` hoặc `json`. Các mặc định là `OPS_OLDEST_JOB_SECONDS=300`, `OPS_FAILURE_RATE_THRESHOLD=0.20`, `OPS_MIN_TERMINAL_JOBS=5` và `OPS_ALERT_COOLDOWN_SECONDS=900`. Backend kiểm tra mỗi 60 giây khi đang chạy. Cooldown nằm trong bộ nhớ tiến trình. Trong khung demo, có thể bật UptimeRobot kiểm tra HTTPS mỗi năm phút. Cảnh báo nghiệp vụ cần Backend đang chạy, và Render Free có thể ngủ hoặc khởi động lại.

Khi cảnh báo tuổi job xuất hiện, kiểm tra Worker `/health`, lỗi trong log và trạng thái Outbox. Event hết retry chuyển sang `FAILED`. Nếu callback cũng lỗi khi cạn retry, kiểm tra trạng thái ảnh và đưa đúng event về hàng đợi sau khi khắc phục. Theo dõi photo ID và job ID, chỉ mở log trong môi trường kiểm thử.
