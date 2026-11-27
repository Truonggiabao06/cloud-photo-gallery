# Giai đoạn 3 · Terraform và GitHub Actions

Terraform tạo một Render Static Site cho frontend, một Web Service cho API và một Web Service cho worker, dùng Docker cho hai Web Service. Module Render nằm trong `infra/render`. Các tệp Terraform Cloud Run ở `infra/` phục vụ bản triển khai GCP trước đây.

| Môi trường | GitHub branch | Terraform workspace | Cách deploy qua Actions |
| --- | --- | --- | --- |
| Staging | `integration/render-supabase-phase3` | `staging` | Push hoặc chọn staging khi chạy thủ công |
| Prod | `main` | `prod` | Chọn prod khi chạy thủ công từ main |

Cả hai Web Service dùng plan `free`. Staging và prod cần nhóm biến, Supabase project và thông tin truy cập riêng. Workspace Render chia sẻ số giờ Free giữa các Web Service, nên dựng staging trước để kiểm tra bài. Render có thể bắt đầu deploy đầu tiên khi tạo dịch vụ. Các lần push chỉ kích hoạt deploy qua Actions sau khi bạn bật biến cho môi trường. Prod ở đây là tên môi trường của bài tập, với các giới hạn của plan Free. [Giới hạn Render Free](https://render.com/docs/free)

## 1. Chuẩn bị staging

1. Push nhánh Giai đoạn 3 lên GitHub để Render đọc được mã nguồn. Trong Supabase staging, dùng bucket riêng tư `photos`, áp dụng schema và quyền runtime theo [Giai đoạn 2](render-supabase-phase2.md).
2. Mở **Render Dashboard → Environment Groups**, tạo group của staging và ghi lại ID dạng `evg-…` từ URL. Thêm các biến dưới đây vào group. Group dùng chung cho API và worker.
3. Thêm secret file `supabase-ca.crt` vào group, dùng nội dung certificate tải trong Supabase. [Secret files trên Render](https://render.com/docs/configure-environment-variables)

| Biến trong group | Giá trị cần điền |
| --- | --- |
| `DATABASE_URL` | URI Session pooler trên cổng 5432 dùng role runtime `photo_app`. Thêm `?sslmode=verify-full&sslrootcert=%2Fetc%2Fsecrets%2Fsupabase-ca.crt` và mã hóa ký tự đặc biệt trong mật khẩu theo URL. |
| `S3_ACCESS_KEY_ID` | Access Key mới của Supabase Storage S3 staging |
| `S3_SECRET_ACCESS_KEY` | Secret Key mới khớp với Access Key |
| `WORKER_SHARED_SECRET` | Một chuỗi ngẫu nhiên dài dùng chung để worker và API xác thực nhau |
| `OPS_METRICS_TOKEN` | Token riêng cho endpoint metrics nếu dùng phần giám sát |
| `OPS_ALERT_WEBHOOK_URL` | HTTPS webhook nếu cần cảnh báo. Đặt thêm `OPS_ALERT_WEBHOOK_FORMAT` thành `discord`, `slack` hoặc `json` tùy nơi nhận. |

Chỉ nhập khóa, mật khẩu và URI có thông tin đăng nhập trực tiếp vào Render. Terraform nhận ID của group, còn GitHub Actions chỉ nhận Render API key. Các thiết lập CORS, endpoint worker, bucket và Entra đi qua Terraform.

## 2. Tạo dịch vụ bằng Terraform

Chạy trong PowerShell ở thư mục gốc `cloud-photo-gallery`. Tạo bản cấu hình staging một lần.

```powershell
Copy-Item infra/render/staging.tfvars.example infra/render/staging.tfvars
terraform -chdir=infra/render init
terraform -chdir=infra/render workspace select -or-create staging
```

Mở `infra/render/staging.tfvars`, điền Supabase S3 endpoint, region, tên bucket, ID group và thông tin App Registration Entra. `entra.scope` mặc định là `access_as_user`. Điền Render owner ID dạng `tea-…` hoặc `usr-…` lấy từ Settings. PowerShell sẽ hỏi Render API key qua ô nhập ẩn.

```powershell
$env:RENDER_OWNER_ID = Read-Host 'Render owner ID'
$env:RENDER_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Render API key' -AsSecureString)).Password
terraform -chdir=infra/render plan -var-file=staging.tfvars -out=staging.tfplan
terraform -chdir=infra/render apply staging.tfplan
```

Kiểm tra plan có hai Web Service `free`, một Static Site và liên kết group trước khi apply. Sau lần apply đầu, lấy `frontend_url` điền vào `frontend_origin` và `worker_url` điền vào `worker_wake_url`. Dùng URL chính xác từ output, bỏ dấu slash cuối ở hai biến Terraform. Thêm `frontend_url/` vào redirect URI loại SPA của Entra. Chạy lại hai lệnh plan và apply sau khi sửa `staging.tfvars`.

State nằm cục bộ theo Terraform workspace. Giữ bản sao an toàn của state và dùng cùng một bản state khi thay đổi hạ tầng. Mỗi lần sửa nhớ chọn đúng workspace. Chỉ public cấu hình mẫu `*.tfvars.example`.

## 3. Bật deploy qua GitHub Actions

1. Trong repo, mở **Settings → Environments → staging**. Tạo secret `RENDER_API_KEY`. Chỉ định nhánh staging cho môi trường nếu GitHub hỗ trợ triển khai theo nhánh.
2. Chạy lệnh sau trong workspace staging. Thêm từng tên và giá trị xuất ra vào **Environment variables** của môi trường staging.
   ```powershell
   terraform -chdir=infra/render output -json github_environment_variables
   ```
3. Thêm `RENDER_DEPLOY_ENABLED=true` sau cùng. Mở **Actions → Verify and deploy to Render** và xem lần chạy sau khi push. Nút **Run workflow** chỉ xuất hiện khi workflow đã có trên nhánh mặc định. Nếu chưa merge workflow vào `main`, push một commit trên nhánh staging sau khi bật biến để chạy.
4. Job CI chạy test API và worker, build cấu hình frontend, kiểm tra Terraform, audit dependency và quét secret. Sau khi CI pass, job deploy yêu cầu Render build đúng commit, chờ trạng thái `live` và kiểm tra `/health` của API, worker cùng trang chủ frontend. Nếu runner bị GitHub khóa vì billing thì cần xử lý trên GitHub trước khi có log CI.

Với prod, dùng `prod.tfvars.example`, workspace `prod`, group riêng và Supabase project riêng. Thiết lập GitHub environment `prod` theo cùng cách, giới hạn triển khai từ `main` và bật phê duyệt nếu gói GitHub hỗ trợ. Sau khi merge và hoàn tất cấu hình, chọn **Run workflow**, nhánh `main`, đích `prod`. Kiểm tra tải ảnh thật bằng frontend ở môi trường staging trước khi chạy prod.
