# Chi phí và thu dọn

## Kịch bản theo tháng

Ước tính USD cho 730 giờ trong `asia-southeast1` (Singapore), không trừ free tier, thuế, tín dụng học tập hay chiết khấu. Dùng làm ngân sách mô phỏng. Đơn giá giả định được làm tròn và cần đối chiếu SKU đúng tài khoản trước khi bật billing. Kịch bản 1.000 ảnh/tháng, khoảng 5 GiB original và 1 GiB derivative giữ trung bình, 100.000 HTTP request, 3.000 Pub/Sub call/delivery, 5 GiB egress Internet. Giữ tối đa 2/3/3 instances Frontend/Backend/Worker và min 0. Giả định tổng active runtime 10 giờ ở 1 vCPU và trung bình 0,5 GiB, gồm đo lường storage và test.

| Hạng mục | Giả định tính | USD/tháng |
| --- | --- | ---: |
| Cloud Run request-based cho services và execution của storage job | Ước `36.000 × $0,000035` CPU + `18.000 × $0,000004` RAM + `0,1 triệu × $0,40` request; giả định đơn giá tổng hợp bảo thủ | 1,37 |
| Cloud Storage Standard regional | 6 GiB × $0,025 + 10.000 Class A × $0,006/1.000 + 100.000 Class B × $0,0005/1.000. Bao gồm list định kỳ và đọc ảnh | 0,26 |
| Internet egress | 5 GiB × $0,15/GiB hệ số dự toán cho Internet APAC. Đối chiếu đích và SKU khi chốt | 0,75 |
| Pub/Sub | 0,05 GiB qua publish và delivery, gồm retry/retention mẫu; dự phòng $0,05 | 0,05 |
| Artifact Registry | Giữ 3 GiB × $0,10/GiB | 0,30 |
| Secret Manager | Ba active versions × $0,06, 2.000 access operations × $0,03/10.000 | 0,19 |
| Scheduler + observability | Một Scheduler job $0,10; dự phòng $2,00 cho khoảng 0,5 GiB log, hai custom gauges tần suất thấp, alert và các query dashboard | 2,10 |
| **GCP cơ sở** | Chưa gồm database và NAT | **5,02** |
| Cloud SQL PostgreSQL 15 Enterprise, ZONAL, tùy chọn | Shared core db-f1-micro 730 × $0,015; SSD 10 GiB × $0,23; backup 5 GiB × $0,10; giữ bảy backup. Giả định backup thực dùng 5 GiB, không nhân lên theo dung lượng provisioned | **13,75** |
| Cloud NAT cho Atlas public, tùy chọn | IPv4 730 × $0,005; dự phòng gateway theo mức sử dụng tối đa 1 equivalent trong 730 giờ × $0,0014; 5 GiB qua NAT × $0,045 | **4,90** |
| MongoDB Atlas | Hóa đơn riêng theo tier, region, backup, egress và limit của nhóm. Nếu đủ điều kiện free tier thì có thể $0; kiểm tra Atlas. Thay bằng chi phí thực khi nộp. | theo tier |

Tổng dự toán **$18,77/tháng với SQL và không NAT**, hoặc **$9,92/tháng cộng Atlas** khi dùng NAT. GitHub Actions và Microsoft Entra theo quota/tier của tổ chức. Mức dùng job/retention/p95 load khác giả định thì thay số trước khi trình bày. Cấu hình demo không có Cloud Load Balancer riêng. Dashboard memory/CPU và Billing Reports dùng để đối chiếu.

Trong Billing → Budgets & alerts, tạo ngân sách project ví dụ $25 USD/tháng, gửi email ở 50%, 80%, 100% thực tế và ngưỡng forecast. **Budget alert không phải hard cap.** Dừng test dài hạn bằng thời lượng/giới hạn instances và destroy staging khi xong. Giá tham khảo: [Cloud Run](https://cloud.google.com/run/pricing) · [Storage](https://cloud.google.com/storage/pricing) · [Pub/Sub](https://cloud.google.com/pubsub/pricing) · [Cloud SQL](https://cloud.google.com/sql/pricing) · [Artifact Registry](https://cloud.google.com/artifact-registry/pricing) · [NAT](https://cloud.google.com/nat/pricing) · [Secret Manager](https://cloud.google.com/secret-manager/pricing) · [Monitoring](https://cloud.google.com/stackdriver/pricing) · [Scheduler](https://cloud.google.com/scheduler/pricing).

## Checklist trước khi xóa

1. Xác minh đúng project, workspace Terraform, prefix và bucket. Lưu evidence, sơ đồ, revision IDs, billing và bản backup được duyệt. Khi có SQL, kiểm tra kết nối backup và quyền khôi phục đã được xác nhận.
2. Dừng upload và mọi workflow deploy đang chạy. Tắt workflow trước destroy nếu repo staging riêng. Kiểm tra Terraform state còn đủ.
3. Xóa object staging trong bucket theo tên đã xác minh. Bucket Terraform có `force_destroy = false` để destroy yêu cầu bucket trống. Soft delete tắt ngay từ khi tạo để tránh phí dữ liệu đã xóa. Nếu nhóm thay chính sách, theo dõi riêng object soft-deleted đến expiry.
4. Review destroy plan, sau đó chạy destroy có prompt xác nhận. Không dùng `-auto-approve` cho thao tác có dữ liệu.

```bash
terraform -chdir=infra workspace show
terraform -chdir=infra state list
BUCKET=$(terraform -chdir=infra output -raw bucket)
gcloud config get-value project
gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT"
gcloud storage ls --all-versions "gs://$BUCKET/**" --project "$PROJECT"
read -rp 'Nhập đúng tên bucket staging để xoá objects: ' CONFIRM_BUCKET
if [ "$CONFIRM_BUCKET" = "$BUCKET" ] && [ -n "$BUCKET" ]; then
  gcloud storage rm --all-versions "gs://$BUCKET/**" --project "$PROJECT"
fi
terraform -chdir=infra plan -destroy
terraform -chdir=infra destroy
```

Nếu bucket vốn trống, lệnh rm wildcard có thể báo không có đối tượng khớp. Xác minh bucket trống trước khi tiếp tục. Nếu project bật retention hoặc object hold, thực hiện đúng thời hạn lưu dữ liệu. Với SQL, nếu nhóm đã bật deletion protection ngoài cấu hình mẫu, gỡ bảo vệ có chủ đích và apply sau khi xác nhận backup. Xác minh thao tác xong:

```bash
terraform -chdir=infra state list
gcloud run services list --region "$REGION" --project "$PROJECT"
gcloud run jobs list --region "$REGION" --project "$PROJECT"
gcloud scheduler jobs list --location "$REGION" --project "$PROJECT"
gcloud sql instances list --project "$PROJECT"
gcloud compute addresses list --project "$PROJECT"
gcloud compute routers list --project "$PROJECT"
gcloud storage buckets list --project "$PROJECT"
gcloud artifacts repositories list --location "$REGION" --project "$PROJECT"
gcloud pubsub topics list --project "$PROJECT"
gcloud pubsub subscriptions list --project "$PROJECT"
gcloud secrets list --project "$PROJECT"
```

Đối chiếu prefix của deployment đã xóa. Kiểm tra Cloud SQL retained/on-demand backup hoặc final backup trong Console nếu nhóm đã cấu hình giữ, bucket state riêng và log sink/export ngoài Terraform. Nếu bật Atlas, dọn cluster/backup, DB user và NAT allowlist trong Atlas sau thời hạn nghiệm thu. Xóa GitHub vars/Entra demo registration riêng nếu không dùng chung; xác minh chính sách retention của log và WIF soft delete. Terraform giữ API enable để những workload khác trong project tiếp tục hoạt động. Xem Billing Reports sau khi chi phí đã cập nhật, đối chiếu theo SKU và ngày destroy.
