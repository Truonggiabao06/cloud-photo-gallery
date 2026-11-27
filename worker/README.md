# Worker của TV 3

Đặt `package.json`, `package-lock.json`, và code Node trong `src/`. `npm start` lắng nghe `0.0.0.0:$PORT`. Mẫu chạy trên Debian slim với UID `node`. Nếu team chọn runtime hoặc layout khác, chỉnh Dockerfile và điều kiện phát hiện source trong workflow cùng commit.

Endpoint POST `PUBSUB_PUSH_PATH` (mặc định `/pubsub/push`) đọc Pub/Sub push wrapper. Giải mã Base64 ở `message.data` thành JSON theo [README của TV 2](../backend/README.md#8-worker-contract-member-3) và kiểm tra kiểu dữ liệu. Lưu `message.messageId`, nhận `deliveryAttempt` ở cấp wrapper. Audience OIDC là origin Cloud Run Worker, phần path chỉ dùng để định tuyến. Ingress Internal cho phép Pub/Sub cùng project gọi URL run.app mặc định. Cloud Run xác thực danh tính trước khi request đến handler.

| Biến runtime | Công dụng |
| --- | --- |
| `PORT` | Cloud Run tự cấp 8080 |
| `GCP_PROJECT_ID`, `GCS_BUCKET_NAME` | GCS qua ADC của Cloud Run |
| `DERIVATIVE_PREFIX` | Mặc định `thumbnail/`; ghi `<photoId>/small.jpg` và `<photoId>/large.jpg` bên dưới |
| `BACKEND_BASE_URL`, `WORKER_SHARED_SECRET` | Hợp đồng cũ `PATCH /api/photos/:id/worker-status` với header `x-worker-secret`. Khi sổ job hoàn tất, TV 2/3/4 thống nhất cập nhật có điều kiện và chuyển xác thực workload sang OIDC |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS` | Chỉ cho bản PostgreSQL có hỗ trợ driver, kết nối TLS private IP |

Đề xuất thumbnail JPEG cạnh dài 160 và 480 px, giữ tỷ lệ ảnh và giới hạn kích thước pixel đầu vào. Mỗi derivative tạo với `ifGenerationMatch=0`. Khi đã tồn tại, kiểm tra source generation hoặc mã băm metadata và định dạng trước khi tiếp tục. Ghi trạng thái hoàn tất sau khi có đủ hai ảnh và khi có bằng chứng giao dịch/điều kiện cập nhật phù hợp. Xử lý lỗi loại vĩnh viễn như JPEG hỏng bằng trạng thái `FAILED` với lý do đã làm sạch rồi trả 2xx. Lỗi tạm thời trả non-2xx. Sau khi xác nhận đã hoàn tất hoặc đã dedup một sự kiện, ghi `delivery_ack` và trả 204. Xem [hợp đồng log và failpoint](../docs/monitoring_runbook.md).
