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

Với snapshot TV 2, dùng Atlas. Nếu dùng Atlas public endpoint, bật `enable_static_atlas_egress` để allowlist duy nhất NAT IP /32; dùng database user có quyền đúng DB và bật TLS. Nếu nhóm quản lý kết nối private khác, xác nhận route trước khi deploy. Giữ `app_secrets_ready = false`, `enable_push = false` và `enable_postgres = false` cho lượt đầu.

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

Nếu có NAT, chạy `terraform -chdir=infra output -raw atlas_egress_ip` và allowlist đúng `<IP>/32` trong Atlas.

```bash
MONGO_SECRET=$(terraform -chdir=infra output -json secret_ids | jq -er .MONGODB_URI)
WORKER_SECRET=$(terraform -chdir=infra output -json secret_ids | jq -er .WORKER_SHARED_SECRET)
read -rsp 'MongoDB Atlas URI: ' PHOTO_MONGO_URI
printf '\n'
printf '%s' "$PHOTO_MONGO_URI" | gcloud secrets versions add "$MONGO_SECRET" --data-file=- --project "$PROJECT"
unset PHOTO_MONGO_URI
openssl rand -hex 48 | tr -d '\n' | gcloud secrets versions add "$WORKER_SECRET" --data-file=- --project "$PROJECT"
```

Sửa `app_secrets_ready = true` rồi apply. Terraform chỉ lưu tham chiếu tới secret. Cloud Run tự cấp `PORT=8080` và ADC của runtime SA. Khi xoay secret, điều phối cả hai revision trong staging; env secret được đọc lúc instance khởi động. Có thể pin version số trước khi rollout nếu nhóm cần giữ tương thích rollback. Nếu IAM chưa lan truyền và thấy lỗi quyền ngay sau lượt đầu, kiểm tra thông báo rồi plan/apply lại.

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

WIF/IAM có thể cần vài phút lan truyền. CI bỏ qua thư mục mẫu chưa có app. Xác minh digest của Worker là image thật và endpoint POST khớp `worker_push_path`. Set `enable_push = true`, rồi apply và kiểm tra:

```bash
terraform -chdir=infra plan -out=activate.tfplan
terraform -chdir=infra apply activate.tfplan
PUSH_SUB=$(terraform -chdir=infra output -raw push_subscription)
gcloud pubsub subscriptions describe "$PUSH_SUB" --project "$PROJECT" \
  --format='yaml(pushConfig,ackDeadlineSeconds,retryPolicy,deadLetterPolicy)'
gcloud run services get-iam-policy "$PREFIX-worker" --region "$REGION" --project "$PROJECT"
gcloud storage buckets describe "gs://$(terraform -chdir=infra output -raw bucket)" --project "$PROJECT"
```

Chỉ upload sau khi subscription và DLQ IAM có hiệu lực. Nếu đã upload sớm, kiểm tra topic retention và reconcile job trước khi phát lại có chọn lọc. Đăng nhập Frontend bằng owner, thử một ảnh và xác minh Worker và ký GET. Worker chạy với ingress Internal và IAM Invoker. Pub/Sub cùng project gọi URL `run.app` mặc định. Khi thấy push 401/403/404, kiểm tra URL/audience, path, push SA và IAM. Khi API không khởi động, kiểm tra Atlas allowlist, URI đã URL-encode password, DB user và NAT.

## 4. Chạy QA và lưu bằng chứng

Lấy hai delegated API access token thật từ hai phiên MSAL. Dùng DevTools xem request gọi API của ứng dụng demo. Token cần còn đủ thời hạn và đúng audience/scope. Người thứ hai chưa được mời vào album QA. ADC của Cloud Shell cần GCS objectViewer, Pub/Sub publisher và `roles/logging.viewer` trong staging; thêm `storage.buckets.get` nếu dùng `--check-bucket-iam`. Kiểm thử invited viewer theo route chia sẻ thật sau khi TV 2 triển khai.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r tests/requirements.txt
export QA_PROJECT="$PROJECT" QA_API_URL="$BACKEND_URL" QA_WORKER_URL="$WORKER_URL"
export QA_WORKER_SERVICE="$PREFIX-worker"
QA_BUCKET=$(terraform -chdir=infra output -raw bucket)
QA_TOPIC=$(terraform -chdir=infra output -raw topic)
export QA_BUCKET QA_TOPIC QA_DERIVATIVE_PREFIX=thumbnail/
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

Test 1 dùng 100 JPEG tổng hợp; Test 3 dùng 5 tệp có đuôi và MIME JPEG nhưng bytes hỏng để đi qua API hiện tại. QA kiểm tra hai derivative JPEG theo prefix mặc định và cạnh dài 160/480 px; truyền `--small-size`, `--large-size` nếu nhóm thống nhất giá trị khác. Kết quả JSON và fixtures trong `evidence/`. Test 2 cần các log từ runbook và nộp thêm bằng chứng đọc ledger của TV 4. Load dùng status của bộ ID Test 1 đã pass. Nếu gặp 429 với limiter 300/15 phút, giữ kết quả để gửi TV 2 và chạy lại cửa sổ mới hoặc bản đã sửa.

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

## 6. Cloud SQL PostgreSQL 15 tùy chọn

Bật `enable_postgres` và apply để dựng instance chỉ có private IP. Backend/Worker dùng Direct VPC Egress. TV 2/4 chuyển driver, schema và migration trước khi dùng DB. App có thể dùng driver TCP TLS với xác minh CA, hoặc Cloud SQL connector private IP sau khi thêm quyền `roles/cloudsql.client` cho runtime tương ứng. Trước khi tạo user, TV 4 chạy `CREATE ROLE photo_runtime NOLOGIN;` bằng PostgreSQL admin từ môi trường trong VPC, rồi cấp quyền theo schema triển khai. Tạo mật khẩu ngoài state:

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

Chờ operation hoàn thành. TV 4 chạy migration từ môi trường được cấp quyền VPC, tách migration role và quyền app. Set `postgres_secret_ready = true` rồi apply. Snapshot TV 2 vẫn cần `MONGODB_URI`. Khi chuyển app hoàn toàn, phối hợp TV 2/4 để dọn binding và phiên bản Mongo cũ sau thời hạn rollback.

## 7. Recreate

Lưu evidence và chạy [cleanup](cost_and_cleanup.md) với đúng state. Set `enable_push = false`, `app_secrets_ready = false`, `postgres_secret_ready = false`. Chọn prefix mới nếu dựng lại ngay trong cùng project vì WIF Pool/Provider giữ tên soft-delete khoảng 30 ngày; đổi bucket nếu tên chưa dùng lại được. Dùng tên SQL mới nếu tên đã xoá còn bị giữ. Lặp bước 1–4, nạp secret phiên bản mới, cập nhật GitHub vars và redirect URI. Lưu plan, workflow run, smoke và revision của lần recreate. [Rollback Cloud Run](https://cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration) · [Static egress](https://cloud.google.com/run/docs/configuring/static-outbound-ip) · [Pub/Sub push](https://cloud.google.com/run/docs/tutorials/pubsub).
