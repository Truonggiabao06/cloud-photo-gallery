# Worker Python · Pub/Sub push

Cloud Run chạy `push_app:create_app()` qua Gunicorn, lắng nghe `PORT` mặc định 8080. Terraform cấu hình ingress Internal và IAM Invoker cho Pub/Sub push service account. Giữ Worker ở chế độ private. Cloud Run xác minh OIDC trước khi chuyển yêu cầu tới Worker.

- `GET /healthz` kiểm tra tiến trình HTTP.
- `POST /pubsub/push` nhận Pub/Sub push dạng wrapped JSON. Cấu hình đường dẫn bằng `PUBSUB_PUSH_PATH`.
- `204` xác nhận sự kiện đã xử lý hoặc lỗi vĩnh viễn đã được handler hiện tại xử lý. `503` yêu cầu Pub/Sub giao lại. Wrapper sai trả `400` và Pub/Sub có thể tiếp tục giao theo retry/DLQ.
- Worker dùng `BACKEND_BASE_URL` do Terraform truyền. `BACKEND_API_BASE_URL` vẫn dùng được để chạy local. Push cần `GCP_PROJECT_ID`, `GCS_BUCKET_NAME` và secret `WORKER_SHARED_SECRET`. Dùng ADC khi truy cập GCS. Đặt `app_secrets_ready = true` sau khi Secret Manager đã có version và trước khi deploy Worker thật.
- Giữ `derivative_prefix = "thumbnail/"` vì code Worker hiện ghi `thumbnail/small/<photoId>.webp` và `thumbnail/large/<photoId>.webp`. Backend MongoDB hiện lưu key ảnh lớn trong `thumbnailObject`. Bản này sử dụng hợp đồng `PHOTO_UPLOADED` hiện có.
- `python main.py` vẫn chạy chế độ pull. Chế độ đó cần `PUBSUB_TOPIC` và `PUBSUB_SUBSCRIPTION`.

## Thử local trên Windows

Trong PowerShell từ thư mục gốc repo:

```powershell
cd .\worker
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -v
```

Các bài test kiểm tra HTTP push wrapper, ACK/NACK, quyền đi qua Backend callback giả lập và xử lý ảnh, không cần GCP billing. Gunicorn dùng trong container Linux. Nút chạy Cloud Run cần project billing và IAM đã cấu hình.

## Ghép vào nhánh tích hợp

Giải nén gói ở ngoài repo rồi copy thư mục `worker` và `.github` vào thư mục gốc `cloud-photo-gallery` trên nhánh `integration/worker-push`. Bản workflow cập nhật đã giữ cấu hình build Frontend tĩnh và nhận Worker Python dựa trên `push_app.py` cùng `requirements.txt`.

Hãy giữ `enable_push = false` trong khi tích hợp. Bật push sau khi secret đã nạp, Worker thật đã deploy và Cloud Run Invoker đã xác minh. Gói hiện tại chưa có sổ dedup PostgreSQL hay structured terminal commit log. Khi chạy bộ cloud QA, đồng bộ quy ước thumbnail WebP và hợp đồng log với Backend/Worker bản cuối.
