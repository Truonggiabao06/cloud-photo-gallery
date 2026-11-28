# Triển khai từ Google Cloud Shell

## 0. Chuẩn bị

Dùng một project GCP staging riêng đã bật billing, một repo GitHub của nhóm và hai người dùng demo trong cùng tenant Entra. Người apply cần quyền tạo tài nguyên Service Usage, IAM, Run, Artifact Registry, Storage, Pub/Sub, Secret Manager, Logging, Monitoring, Scheduler và Compute/SQL nếu bật. Xác nhận tổ chức cho phép hai dịch vụ public bằng tùy chọn tắt Invoker IAM check. Trong Cloud Shell:

```bash
read -rp 'GCP project ID: ' PROJECT
export PROJECT REGION=asia-southeast1 PREFIX=photo07
gcloud config set project "$PROJECT"
gcloud billing projects describe "$PROJECT"
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com --project "$PROJECT"
gcloud auth application-default print-access-token >/dev/null
# Nếu chưa có ADC, chạy gcloud auth application-default login.
terraform version
gh --version
```

Nếu Cloud Shell thiếu Terraform từ 1.9, cài phiên bản dùng trong CI:

```bash
mkdir -p "$HOME/.local/bin"
TF_TMP=$(mktemp -d)
(
  cd "$TF_TMP" &&
    curl -fSLO https://releases.hashicorp.com/terraform/1.11.4/terraform_1.11.4_linux_amd64.zip &&
    curl -fSLO https://releases.hashicorp.com/terraform/1.11.4/terraform_1.11.4_SHA256SUMS &&
    grep ' terraform_1.11.4_linux_amd64.zip$' terraform_1.11.4_SHA256SUMS | sha256sum -c - &&
    unzip -o terraform_1.11.4_linux_amd64.zip terraform -d "$HOME/.local/bin"
)
export PATH="$HOME/.local/bin:$PATH"
terraform version
```

## 1. Cấu hình repo, Entra và Terraform

Tải ZIP qua nút Upload của Cloud Shell. Với repo mới, dùng thư mục giải nén làm root. Với repo đã có code, chép các file TV 5 vào repo nhóm, giữ source/manifest/lockfile của từng app. Cập nhật lockfile backend bằng `npm install --package-lock-only` nếu manifest đã đổi.

```bash
mkdir -p "$HOME/photo07"
unzip "$HOME/member5-devops-qa-gcp.zip" -d "$HOME/photo07"
cd "$HOME/photo07"
read -rp 'GitHub repo (owner/name): ' GH_REPO
export GH_REPO
gh auth status
# Nếu chưa liên kết GitHub CLI, chạy gh auth login.
gh api "repos/$GH_REPO" --jq '{repository: .full_name, repository_id: .id, owner_id: .owner.id, branch: .default_branch}'
cp infra/terraform.tfvars.example infra/terraform.tfvars
nano infra/terraform.tfvars
```

Điền project, bucket duy nhất toàn cầu, GitHub repo chính xác cùng repo ID/owner ID, Entra tenant ID/API client ID, email alert và `qa_principals` dạng `["user:qa@example.com"]`. Trong Entra → App registrations, tạo app API single-tenant, đặt `api.requestedAccessTokenVersion = 2` trong manifest và expose delegated scope mặc định `access_as_user` dưới Application ID URI `api://<API_APP_ID>`. Tạo SPA registration riêng, thêm delegated permission cho scope đó và cấp consent theo chính sách tenant. Audience mặc định là API client ID. Nếu đổi nhánh, khớp biến `deploy_branch`, `on.push.branches` trong workflow và lệnh `--ref` bên dưới. Khớp region/prefix với biến shell.

Dùng [Cloud SQL PostgreSQL 15](postgresql.md) với `enable_postgres = true` và `derivative_prefix = "thumbnails/"`. Giữ `app_secrets_ready = false`, `postgres_secret_ready = false` và `enable_push = false` cho lượt đầu.

```bash
terraform -chdir=infra fmt -check
terraform -chdir=infra init
terraform -chdir=infra validate
terraform -chdir=infra plan -out=bootstrap.tfplan
terraform -chdir=infra apply bootstrap.tfplan
terraform -chdir=infra output
```

State mặc định nằm ở Cloud Shell. Dùng một operator hoặc chuyển sang GCS backend riêng do nhóm quản lý, có PAP, UBLA, versioning và quyền IAM hẹp. Sau khi tạo state bucket, khai báo `backend "gcs" {}` trong khối `terraform` rồi chạy `terraform -chdir=infra init -migrate-state -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=$PREFIX/staging"`. Giữ state đến khi kiểm tra destroy xong. Không commit tfvars, secret, plan hoặc state.

## 2. Nạp Secret Manager và publish cấu hình

Hoàn thành phần Cloud SQL ở mục 6 trước khi bật các secret.

```bash
WORKER_SECRET=$(terraform -chdir=infra output -json secret_ids | jq -er .WORKER_SHARED_SECRET)
openssl rand -hex 48 | tr -d '\n' | gcloud secrets versions add "$WORKER_SECRET" --data-file=- --project "$PROJECT"
```

Sau khi tạo user `photo_app`, thêm phiên bản `DB_PASS` và chạy migration, đặt `app_secrets_ready = true` và `postgres_secret_ready = true` trong tfvars.

```bash
terraform -chdir=infra plan -out=secrets.tfplan
terraform -chdir=infra apply secrets.tfplan
FRONTEND_URL=$(terraform -chdir=infra output -raw frontend_url)
BACKEND_URL=$(terraform -chdir=infra output -raw backend_url)
WORKER_URL=$(terraform -chdir=infra output -raw worker_url)
export FRONTEND_URL BACKEND_URL WORKER_URL
```

Đăng ký origin Frontend và callback path thật trong Entra loại SPA.

## 3. CI/CD và bật push sau khi có Worker thật

```bash
terraform -chdir=infra output -json github_variables |
  jq -r 'to_entries[] | [.key,.value] | @tsv' |
  while IFS=$'\t' read -r key value; do
    gh variable set "$key" --repo "$GH_REPO" --body "$value" || exit 1
  done
read -rp 'Entra SPA application client ID (ZIP nhóm: 3430b068-b6f1-4df0-a4d7-c189af8dcd07): ' SPA_CLIENT_ID
gh variable set VITE_ENTRA_CLIENT_ID --repo "$GH_REPO" --body "$SPA_CLIENT_ID"
gh variable list --repo "$GH_REPO"
```

Source tĩnh của Frontend được build từ index.html, CSS và JS theo [hướng dẫn Frontend](../frontend/README.md). Dùng [hướng dẫn Worker](../worker/README.md) để nhập Worker tương thích Pub/Sub push. Merge lên nhánh đã cấu hình với quy trình Git của nhóm. Một repo mới có thể dùng:

```bash
git init -b main
git add .github .gitignore README.md infra backend frontend worker docs tests
git commit -m "Add GCP deployment and QA"
git remote add origin "https://github.com/$GH_REPO.git"
gh auth setup-git
git push -u origin main
```

Chỉ dùng lệnh trên khi repo đích chưa có lịch sử. Với repo đang dùng, tạo branch từ lịch sử repo và merge qua pull request của nhóm. Sau khi workflow có trên nhánh mặc định:

```bash
gh workflow run deploy.yml --repo "$GH_REPO" --ref main -f service=all
gh run list --repo "$GH_REPO" --workflow deploy.yml --limit 5
gh run watch --repo "$GH_REPO"
curl -fsS "$BACKEND_URL/api/health" | jq -e '.status == "OK"'
for service in frontend backend worker; do
  gcloud run services describe "$PREFIX-$service" --region "$REGION" --project "$PROJECT" \
    --format='yaml(status.url,status.latestReadyRevisionName,status.traffic)'
done
```

WIF/IAM có thể cần vài phút lan truyền. CI bỏ qua thư mục mẫu chưa có app. Xác minh Worker và Job `$PREFIX-outbox` đã dùng image vừa build, và endpoint POST của Worker khớp `worker_push_path`. Đặt `enable_push = true` rồi apply để tạo subscription và lịch relay.

```bash
terraform -chdir=infra plan -out=activate.tfplan
terraform -chdir=infra apply activate.tfplan
PUSH_SUB=$(terraform -chdir=infra output -raw push_subscription)
gcloud pubsub subscriptions describe "$PUSH_SUB" --project "$PROJECT" \
  --format='yaml(pushConfig,ackDeadlineSeconds,retryPolicy,deadLetterPolicy)'
gcloud run services get-iam-policy "$PREFIX-worker" --region "$REGION" --project "$PROJECT"
gcloud storage buckets describe "gs://$(terraform -chdir=infra output -raw bucket)" --project "$PROJECT"
```

Chỉ upload sau khi subscription và DLQ IAM có hiệu lực. Nếu đã upload sớm, kiểm tra topic retention và reconcile job trước khi phát lại có chọn lọc. Đăng nhập Frontend bằng owner, thử một ảnh và xác minh Worker và ký GET. Worker chạy với ingress Internal và IAM Invoker. Pub/Sub cùng project gọi URL `run.app` mặc định. Khi thấy push 401/403/404, kiểm tra URL/audience, path, push SA và IAM. Khi API không khởi động, kiểm tra đường dẫn VPC, quyền Cloud SQL Client, DB user, Secret Manager và migration.

## 4. Chạy QA và lưu bằng chứng

Lấy hai delegated API access token thật từ hai phiên MSAL. Dùng DevTools xem request gọi API của ứng dụng demo. Token cần còn đủ thời hạn và đúng audience/scope. Người thứ hai chưa được mời vào album QA. ADC của Cloud Shell cần GCS objectViewer, Pub/Sub publisher và `roles/logging.viewer` trong staging; thêm `storage.buckets.get` nếu dùng `--check-bucket-iam`. Bộ QA kiểm tra truy cập trước và sau khi owner mời viewer, rồi thử upload bằng tài khoản viewer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tests/requirements.txt
export QA_PROJECT="$PROJECT" QA_API_URL="$BACKEND_URL" QA_WORKER_URL="$WORKER_URL"
export QA_WORKER_SERVICE="$PREFIX-worker"
QA_BUCKET=$(terraform -chdir=infra output -raw bucket)
QA_TOPIC=$(terraform -chdir=infra output -raw topic)
export QA_BUCKET QA_TOPIC QA_DERIVATIVE_PREFIX=thumbnails/
read -rsp 'Owner Entra access token (không gồm Bearer): ' QA_OWNER_TOKEN
printf '\n'
read -rsp 'Other user Entra access token: ' QA_OTHER_TOKEN
printf '\n'
export QA_OWNER_TOKEN QA_OTHER_TOKEN
python tests/qa_suite.py run --worker-path /pubsub/push --timeout 300 --replay-timeout 180
RUN_JSON=$(ls -1t evidence/*-run.json | head -n 1)
jq '.checks | map_values({passed,failure})' "$RUN_JSON"
python tests/qa_suite.py load --from-run "$RUN_JSON" --warmup 5 --duration 30 --concurrency 4 --rps 2
LOAD_JSON=$(ls -1t evidence/*-load.json | head -n 1)
jq '.parameters, .summary' "$LOAD_JSON"
unset QA_OWNER_TOKEN QA_OTHER_TOKEN
```

Test 1 dùng 100 JPEG tổng hợp; Test 3 dùng 5 tệp có đuôi và MIME JPEG nhưng bytes hỏng để đi qua API hiện tại. QA kiểm tra hai thumbnail WebP theo prefix mặc định và cạnh dài 200/800 px; truyền `--small-size`, `--large-size` nếu nhóm thống nhất giá trị khác. Kết quả JSON và fixtures trong `evidence/`. Test 2 cần các log từ runbook và nộp thêm bằng chứng đọc ledger của TV 4. Load dùng status của bộ ID Test 1 đã pass. Nếu gặp 429 với limiter 300/15 phút, giữ kết quả để gửi TV 2 và chạy lại cửa sổ mới hoặc bản đã sửa.

## 5. Rollback Cloud Run

```bash
SERVICE="$PREFIX-backend"
gcloud run revisions list --service "$SERVICE" --region "$REGION" --project "$PROJECT"
read -rp 'Revision tốt đã xác minh: ' GOOD_REV
gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='yaml(status.traffic)'
gcloud run services update-traffic "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --to-revisions "$GOOD_REV=100"
gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='yaml(status.traffic)'
curl -fsS "$BACKEND_URL/api/health" | jq -e '.status == "OK"'
```

Lưu trạng thái trước/sau, chạy smoke có auth. Với Worker, kiểm tra ACK và job mới sau rollback. Dùng `--to-revisions "$NEW_REV=100"` để quay lại revision mới đã xác minh. Schema phải tương thích ngược nếu rollback code. Terraform bỏ qua image và traffic. Khi apply thay đổi template, kiểm tra `status.traffic`; nếu traffic còn pin bản cũ, promote revision cấu hình mới sau smoke hoặc deploy qua CI.

## 6. Cloud SQL PostgreSQL 15

Kết nối vào `cloud_gallery` từ máy trong VPC bằng tài khoản migration. Chạy ba script sau với `psql -v ON_ERROR_STOP=1`, theo thứ tự.

1. `db/01_database_schema.sql`
2. `db/04_backend_integration.sql`
3. `db/05_runtime_permissions.sql`

Sau khi role `photo_runtime` đã có, chạy lệnh sau trong Cloud Shell để cấp mật khẩu và tạo `photo_app` với role đó.

```bash
DB_SECRET=$(terraform -chdir=infra output -json secret_ids | jq -er .DB_PASS)
read -rsp 'Mật khẩu mạnh cho photo_app: ' PHOTO_DB_PASS
printf '\n'
printf '%s' "$PHOTO_DB_PASS" | gcloud secrets versions add "$DB_SECRET" --data-file=- --project "$PROJECT"
unset PHOTO_DB_PASS
gcloud secrets versions access latest --secret="$DB_SECRET" --project="$PROJECT" | \
  python3 -c '
import json, subprocess, sys, urllib.request
project, instance = sys.argv[1:]
token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
body = json.dumps({"name":"photo_app","password":sys.stdin.read(),"type":"BUILT_IN","databaseRoles":["photo_runtime"]}).encode()
url = f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{project}/instances/{instance}/users"
req = urllib.request.Request(url, body, {"Authorization": f"Bearer {token}", "Content-Type":"application/json"})
with urllib.request.urlopen(req, timeout=30) as response:
    print(json.load(response)["name"])
' "$PROJECT" "$PREFIX-pg15"
gcloud sql operations list --instance "$PREFIX-pg15" --project "$PROJECT" --limit 5
```

Chờ operation hoàn thành rồi quay lại mục 2 để bật secret.

## 7. Recreate

Lưu evidence và chạy [cleanup](cost_and_cleanup.md) với đúng state. Set `enable_push = false`, `app_secrets_ready = false`, `postgres_secret_ready = false`. Chọn prefix mới nếu dựng lại ngay trong cùng project vì WIF Pool/Provider giữ tên soft-delete khoảng 30 ngày; đổi bucket nếu tên chưa dùng lại được. Dùng tên SQL mới nếu tên đã xoá còn bị giữ. Lặp bước 1–4, nạp secret phiên bản mới, cập nhật GitHub vars và redirect URI. Lưu plan, workflow run, smoke và revision của lần recreate. [Rollback Cloud Run](https://cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration) · [Static egress](https://cloud.google.com/run/docs/configuring/static-outbound-ip) · [Pub/Sub push](https://cloud.google.com/run/docs/tutorials/pubsub).

## Nghiệm thu và rollback trên Render

Làm theo [Phase 3](render-supabase-phase3.md) để provision môi trường. API và Worker phải cùng bucket và runtime DB role. Setup Supabase project, bucket, TLS pooler và login runtime là các bước quản trị riêng, Terraform Render quản lý ba service và liên kết nhóm môi trường.

Cài `tests/requirements.txt` vào virtualenv. Đặt `QA_CONFIRM_STAGING=yes`, `QA_API_URL` là origin staging, và `QA_OWNER_TOKEN`, `QA_VIEWER_TOKEN`, `QA_OUTSIDER_TOKEN` là access token API của ba tài khoản Entra thử riêng biệt. Truyền `DATABASE_URL`, `S3_ENDPOINT`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID` và `S3_SECRET_ACCESS_KEY` từ môi trường riêng của staging. Dùng Session pooler với verify-full, ghi nhận SHA đang live, và chạy:

```sh
python tests/render_qa.py acceptance
python tests/render_qa.py load --photo-id <samplePhotoId> --warmup 5 --duration 30 --concurrency 4 --rps 4
```

Acceptance tạo một album mới và 105 fixture tổng hợp mỗi lần, dùng API upload thật. Test 2 giao lại event đã hoàn tất thêm năm lần. Gói JSON trong `evidence/` chứa timestamp, hash đầu vào, photo ID và kết quả. Load đo p95 nearest rank trên mẫu HTTP 200 sau warmup. Khởi động API và Worker trước khi đo. Script SQL seed là lựa chọn kiểm tra DB riêng. Chỉ đặt `photo.seed_bucket` sau khi nạp object thật vào đúng key hoặc dùng acceptance để API tạo dữ liệu từ đầu.

### Rollback staging

1. Ghi SHA, deploy ID và kết quả health hiện tại. Dừng các lượt deploy tiếp theo của GitHub Actions trong khi rollback. Xác nhận schema DB hiện tại tương thích với bản tốt.
2. Trong Render Deploys của service bị ảnh hưởng, chọn deploy thành công đã biết và **Rollback**. Nếu artifact đã hết retention, dùng **Manual Deploy → Deploy a specific commit** với SHA tốt. Nếu API và Worker đổi hợp đồng, đưa cả hai về cặp phiên bản tương thích.
3. Xác nhận SHA mới live, API và Worker `/health`, đăng nhập, xem album riêng và upload một ảnh thử mới. Lưu timestamp, deploy ID trước/sau và kết quả smoke đã lọc. PostgreSQL và Storage giữ dữ liệu qua rollback, nên không restore DB hoặc xóa object chỉ vì rollback code. [Render Rollbacks](https://render.com/docs/rollbacks).
