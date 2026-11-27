# PostgreSQL cho Cloud Photo Gallery

Ứng dụng dùng PostgreSQL 15. `db/01_database_schema.sql` là schema gốc của thành viên 4. Migration `db/04_backend_integration.sql` thêm tiến độ xử lý, mã Pub/Sub và lease của relay. Backend ghi ảnh, job và Outbox trong một giao dịch. Worker tạo hai thumbnail theo key sinh trong bảng `images` và callback để ghi trạng thái kết thúc cùng một bản ghi dedup. GCS lưu file gốc và file WebP.

## Chạy local với database trống

Từ thư mục gốc repo, tạo database bằng PostgreSQL 15 và chạy hai migration. Dùng tài khoản có quyền tạo extension và bảng.

```powershell
createdb -U postgres cloud_gallery
psql -U postgres -d cloud_gallery -v ON_ERROR_STOP=1 -f db/01_database_schema.sql
psql -U postgres -d cloud_gallery -v ON_ERROR_STOP=1 -f db/04_backend_integration.sql
```

Có thể chạy `02_seed_data.sql` rồi `03_database_testing.sql` trên một database kiểm thử riêng. Script seed tạo metadata minh họa và sự kiện `IMAGE_UPLOADED`. Relay ứng dụng xử lý sự kiện `PHOTO_UPLOADED` từ upload thật.

Sao chép `backend/.env.example` thành `backend/.env` và đặt `DATABASE_URL`. Điền các giá trị Entra, GCS, Pub/Sub và secret của Worker. Trong `backend`, chạy `npm ci` rồi `npm start`. Với broker thật, chạy `node src/outbox-relay.js` để phát các event đang chờ. `GET /api/health` trả OK sau khi Backend kết nối được database và thấy migration.

Owner có thể thêm viewer bằng `POST /api/albums/{albumId}/members` với body `{"memberId":"<id của viewer từ GET /api/auth/me>"}`. Viewer xem được album, danh sách ảnh và trạng thái. Upload giữ quyền owner.

## Triển khai GCP

Theo [hướng dẫn triển khai](deploy_guide.md). Backend và Cloud Run Job dùng Cloud SQL Connector qua private IP. Worker gọi API cập nhật trạng thái. Cài schema và hoàn thành cấu hình Secret Manager trước khi deploy image Backend. Sau khi xác nhận image của Job và Worker, đặt `enable_push = true` để tạo subscription và lịch relay mỗi phút.

Để thử một ảnh sau khi subscription đã được tạo, upload trên Frontend rồi đợi lịch relay, hoặc chạy:

```bash
gcloud run jobs execute "$PREFIX-outbox" --region "$REGION" --project "$PROJECT" --wait
```

Nếu relay dừng sau khi publish và trước khi cập nhật PostgreSQL, relay kế tiếp có thể gửi lại sau khi lease hết hạn. Worker giữ nguyên đường dẫn GCS và mỗi ảnh chỉ được ghi kết thúc một lần. Sau tám lỗi publish, event chuyển `FAILED`. Kiểm tra Pub/Sub IAM và log `outbox_publish_failed`. Sau khi xử lý nguyên nhân, có thể đưa event đã xác minh về `PENDING` với `attempts = 0` và `available_at = now()`.
