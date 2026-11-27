# Cloud Photo Gallery Frontend

Ứng dụng HTML/CSS/JS của TV 1, lấy từ ZIP nhóm. Mở demo tại máy cá nhân từ thư mục gốc repo:

```powershell
py -m http.server 5500 --bind 127.0.0.1 --directory .\frontend
```

Mở [http://localhost:5500/](http://localhost:5500/). Demo dùng dữ liệu mẫu trong bộ nhớ. Sau khi tải lại trang, giao diện khởi tạo lại dữ liệu.

## Container và đăng nhập

Frontend không cần Vite hoặc npm build. Dockerfile dùng Node để tạo module cấu hình công khai, sau đó dùng Nginx phục vụ HTML/CSS/JS ở cổng 8080. GitHub Actions dùng lại các biến tên `VITE_*` đã có trong bộ Terraform.

| Biến build | Giá trị |
| --- | --- |
| `VITE_API_BASE_URL` | HTTPS URL của Cloud Run Backend |
| `VITE_ENTRA_TENANT_ID` | Directory (tenant) ID |
| `VITE_ENTRA_CLIENT_ID` | Application (client) ID của app Frontend SPA |
| `VITE_ENTRA_API_SCOPE` | Scope đầy đủ của Backend API, có dạng `api://<backend-client-id>/access_as_user` |

Mặc định cục bộ theo ZIP nhóm: app Frontend `3430b068-b6f1-4df0-a4d7-c189af8dcd07`, Backend API `9300ccc1-a0ef-491a-8740-a4c2c6ed4b80`, tenant `14d5de2b-d212-4175-92d5-156ea5b7c037`. Chủ app cần xác nhận quyền `access_as_user`, access token v2 của Backend và consent trong tenant. Các giá trị deploy lấy từ GitHub Actions Variables thay cho mặc định cục bộ.

Đăng ký SPA redirect URI `http://localhost:5500/` để thử local, và URL gốc Frontend Cloud Run có dấu `/` ở cuối để deploy. Nút đăng nhập dùng MSAL để lấy access token đúng scope và kiểm tra `GET /api/auth/me` trước khi chuyển sang API mode. Frontend dùng multipart `albumId` và `image` cho upload. Bucket, quyền ký URL, Pub/Sub và Worker cần được thiết lập để thử lưu ảnh và xử lý trên GCP.

## Cập nhật bản đang mở trong Antigravity

Sao chép nội dung ZIP vào thư mục gốc `cloud-photo-gallery`, để `frontend/index.html` nằm ngay dưới `frontend/`. Khi sao chép xong, chạy `git status --short` để xem những file được cập nhật. Kiểm tra demo bằng lệnh đầu trang. Giữ file `infra/terraform.tfvars` của máy bạn ngoài Git.

Bản này chuẩn bị việc deploy Frontend. Phần Backend đang dùng GCS/MongoDB trong repo là cơ sở hiện tại. Worker pull và SQL trong ZIP nhóm cần thống nhất với Backend trước khi bật Pub/Sub push hoặc chuyển database. Xem audit và hướng dẫn triển khai của repo.
