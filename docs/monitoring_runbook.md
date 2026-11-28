# Monitoring, alert và phục hồi

Cloud Console → Monitoring → Dashboards → **photo07 | Cloud Photo Operations**. Thay `photo07` bằng prefix đã chọn. Chọn project staging và khoảng 30–60 phút. Để lấy GCS sample ngay:

```bash
gcloud run jobs execute "$PREFIX-storage-meter" --region "$REGION" --project "$PROJECT" --wait
```

| Chỉ số | Nguồn và cách đọc |
| --- | --- |
| Oldest job age | Gauge DB `custom.googleapis.com/<prefix>/oldest_job_age_seconds` gồm job chưa publish. TV 4 cần xuất gauge định kỳ theo tuổi của job chưa terminal cũ nhất, dùng thời gian UTC và 0 khi không còn job. Lấy qua API Monitoring `projects.timeSeries.create` với resource `global` và label `project_id`. Worker SA có metricWriter; nếu sampler chạy riêng, cấp đúng SA của sampler. Biểu đồ cũng có oldest unacked age từ push subscription, chỉ đo sau publish. |
| Processing latency | p95 theo cửa sổ 5 phút từ trường `latencySeconds` khi `job_terminal` và `COMPLETED`. Tính từ event `createdAt` đến durable completion. Gồm backlog, xử lý và retry. |
| Failure rate | Số job `FAILED` chia số logical terminal jobs trong 5 phút, nhân 100. Khi không có job terminal, biểu đồ trống. |
| Retry count | Số structured `job_attempt` với `deliveryAttempt > 1`, cộng 5 phút. Delivery attempt do Pub/Sub tính gần đúng khi DLQ/IAM hoạt động. Năm lần publish của QA có message ID riêng. |
| Derivative storage size | Tổng bytes của các object hiện hành dưới derivative prefix. Cloud Scheduler chạy Cloud Run job 15 phút/lần. Meter đọc từng trang kết quả GCS. Đọc log `derivative_storage_sample` để xác nhận timer và phép đo. |

Nếu chart không có dữ liệu, kiểm tra Worker emit JSON thực, thời gian lấy mẫu, quyền IAM và trạng thái push. Log-based metric chỉ có dữ liệu từ log được ingest sau khi metric đã tạo. Theo dõi thêm DLQ message count và tỷ lệ push 2xx/non-2xx trong Metrics Explorer khi điều tra.

## Alert hành động

| Mục bắt buộc | Cấu hình |
| --- | --- |
| Điều kiện nổ | Subscription push đúng prefix có `subscription/oldest_unacked_message_age > 120s`; ngưỡng 120 giây kiểm tra sau align `ALIGN_MAX`. |
| Khung đánh giá | Align 60 giây, phải vượt ngưỡng liên tục trong retest window 60 giây. Alert bật khi `enable_push = true`. Email lấy từ `alert_email`; xác nhận nhận mail và quyền vào Monitoring. |
| Độ trễ dự kiến | Khoảng 3–6 phút tính từ publish với backlog liên tục. Bao gồm vượt ngưỡng, retest 60 giây, chu kỳ lấy mẫu 60 giây, metric visibility và gửi mail. Đo độ trễ thực tế với Timestamp Pub/Sub, incident và email. |
| Hành động khắc phục đầu tiên | Mở incident, kiểm tra Worker logs theo photoId/jobId/messageId và revision. Nếu trùng revision gây lỗi hoặc failpoint staging, chuyển 100% traffic về revision tốt đã xác minh. Quan sát queue drain và xác nhận đủ hai derivative trước completion. |

## Hợp đồng log để TV 2/3/4 tích hợp

Mỗi dòng là JSON trên stdout. API sinh `requestId`, trả qua response header `X-Request-Id` và đưa vào event nếu nâng schema tương thích. Trong snapshot, liên kết API và Worker bằng `photoId`. Worker thêm `jobId` và `messageId` sau khi nhận push. Dùng UTC ISO-8601, severity và mã lỗi giới hạn. Xử lý một attempt có thể ghi các dòng sau:

```json
{"severity":"INFO","event":"job_attempt","photoId":"fixture-photo","jobId":"fixture-job","messageId":"example-message","deliveryAttempt":2}
{"severity":"WARNING","event":"drill_exit","photoId":"fixture-photo","jobId":"fixture-job","messageId":"example-message","errorCode":"STAGING_EXIT_AFTER_FIRST_DERIVATIVE"}
{"severity":"INFO","event":"job_terminal","photoId":"fixture-photo","jobId":"fixture-job","messageId":"example-message","status":"COMPLETED","latencySeconds":123.4}
{"severity":"INFO","event":"delivery_ack","photoId":"fixture-photo","jobId":"fixture-job","messageId":"example-message"}
```

Chỉ ghi `job_terminal` khi chính attempt này tạo transition terminal đã commit. Với permanent failure, status là `FAILED` và có errorCode đã làm sạch. Ghi `delivery_ack` ngay trước HTTP 204 sau khi bảo đảm đã durable hoặc xác nhận được dedup. Dùng thêm log Cloud Run request status để đối chiếu ACK thực. Tránh log body binary, authorization header, cookie, worker secret, URI/password DB, email cá nhân, tên ảnh gốc, signed URL hay query của URL. Ghi dạng allowlist và chỉ đính kèm bản xuất đã lọc. Tránh dùng requestId/jobId làm label metric.

## Diễn tập staging crash giữa hai derivative và DB completion

Điều kiện chuẩn bị: Test 1–3 đã pass trên revision tốt, staging không có tải của người khác. TV 3 triển khai cờ `QA_CRASH_AFTER_FIRST_DERIVATIVE=1` trên staging, failpoint sau khi ghi/đối chiếu thành công ảnh nhỏ, trước khi ghi ảnh lớn hay commit DB. Dùng 15 giây chờ sau partial write để có khoảng quan sát, ghi log `drill_exit`, sau đó kết thúc process (ví dụ `process.exit(86)` với Node). Những lần retry gặp ảnh nhỏ đã có vẫn đi qua failpoint khi cờ đang bật. Không bật cờ cho production. Chuẩn bị xác nhận IAM và email alert.

```bash
SERVICE="$PREFIX-worker"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='yaml(status.traffic)'
read -rp 'Revision Worker tốt đang nhận 100% traffic: ' GOOD_REV
GOOD_IMG=$(gcloud run revisions describe "$GOOD_REV" --project "$PROJECT" --region "$REGION" --format='value(spec.containers[0].image)')
test -n "$GOOD_IMG"
FAULT_SUFFIX="drill-$(date +%s)"
FAULT_REV="$SERVICE-$FAULT_SUFFIX"
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --image "$GOOD_IMG" \
  --revision-suffix "$FAULT_SUFFIX" --no-traffic --update-env-vars QA_CRASH_AFTER_FIRST_DERIVATIVE=1
gcloud run services update-traffic "$SERVICE" --project "$PROJECT" --region "$REGION" --to-revisions "$FAULT_REV=100"
# Dùng biến QA của deploy guide trước khi chạy.
python tests/qa_suite.py drill
read -rp 'Photo ID từ bằng chứng drill: ' PHOTO_ID
gcloud storage ls "gs://$QA_BUCKET/$QA_DERIVATIVE_PREFIX$PHOTO_ID/"
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE AND jsonPayload.photoId=$PHOTO_ID" \
  --project "$PROJECT" --limit 30 --format='table(timestamp,resource.labels.revision_name,jsonPayload.event,jsonPayload.jobId,jsonPayload.deliveryAttempt)'
```

Quan sát status còn `PENDING`/`PROCESSING`, một ảnh nhỏ, log container exit, retry, backlog và incident. Sau alert hoặc khi gần cạn lượt retry, phục hồi ngay. Max delivery attempts là 10 theo best effort. Chụp alert từ một buổi rehearsal nếu không đợi đủ trong demo 12 phút.

```bash
gcloud run services update-traffic "$SERVICE" --project "$PROJECT" --region "$REGION" --to-revisions "$GOOD_REV=100"
python tests/qa_suite.py drill --photo-id "$PHOTO_ID" --timeout 300
gcloud storage ls "gs://$QA_BUCKET/$QA_DERIVATIVE_PREFIX$PHOTO_ID/"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='yaml(status.traffic)'
```

Xác nhận đủ small/large, 100% progress, một terminal commit, cùng job ID và cửa sổ alert đóng. Nếu job đã vào DLQ, giữ revision tốt, kiểm tra message bằng pull không tự ACK, và đối chiếu nguyên nhân cùng DB lẫn generation. DLQ Pub/Sub bọc message gốc. Sau khi đã khắc phục, lấy data JSON gốc và attributes gốc, publish lại vào topic chính một lần bằng publisher của staging, giữ cùng business ID và đợi job hoàn thành. ACK bản DLQ sau khi đã lưu bằng chứng và xác nhận xử lý; không phát lại toàn bộ DLQ. TV 4 xác nhận sổ job/ProcessedEvent và xử lý terminal failure nếu retry cạn. Khi diễn tập kết thúc, gỡ cờ khỏi service template bằng một lần deploy revision tốt từ CI sau khi loại cờ, hoặc chạy:

```bash
gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --remove-env-vars QA_CRASH_AFTER_FIRST_DERIVATIVE
```

Kiểm tra traffic vẫn chỉ trỏ revision sạch. Nếu app không hỗ trợ cờ, phối hợp để TV 3 đưa một revision failpoint staging theo hợp đồng trên trước khi diễn tập. [Pub/Sub metrics](https://cloud.google.com/monitoring/api/metrics_gcp_p_z) · [Cloud Logging metrics](https://cloud.google.com/logging/docs/logs-based-metrics) · [Cloud Run rollback](https://cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration).

## Failure drill trên Render và Supabase

Chuẩn bị staging riêng, một ảnh tổng hợp và hai phiên bản Worker tốt đã chạy được. Cấu hình `OPS_ALERT_WEBHOOK_URL`, `OPS_METRICS_TOKEN` và nơi nhận alert. API đánh giá tuổi job mỗi 60 giây khi process đang chạy. Có thể hạ `OPS_OLDEST_JOB_SECONDS` xuống 120 cho drill, dự kiến webhook ở lần đánh giá kế tiếp, tức tối đa khoảng 60 giây sau khi vượt ngưỡng nếu API vẫn thức và webhook hoạt động. Tỷ lệ lỗi dùng cửa sổ một giờ. Ghi điều kiện, cửa sổ, thời gian phát hiện và hành động thực tế.

1. Giữ Worker staging tạm dừng. Upload một JPEG tổng hợp hợp lệ, lưu photo ID, job ID và request ID. Xác nhận event còn PENDING và cả hai thumbnail chưa tồn tại.
2. Trên **Worker staging**, đặt `DEPLOY_ENVIRONMENT=staging`, `QA_CRASH_AFTER_FIRST_DERIVATIVE=1`, `QA_DRILL_PHOTO_ID` đúng ID của ảnh thử. Khởi động lại Worker với các biến đó. Điểm ngắt kết thúc process ngay sau PUT ảnh nhỏ và trước PUT ảnh lớn hoặc cập nhật COMPLETED. Chỉ ảnh đã chọn đi qua điểm ngắt.
3. Lưu log `drill_exit`, danh sách object cho thấy chỉ có ảnh nhỏ, trạng thái chưa COMPLETED, biểu đồ backlog và webhook. Hành động đầu tiên khi nhận alert là kiểm tra Worker `/health`, log và lease của event. Chụp ảnh dashboard và alert với timestamp, không đưa token hay URL ký vào evidence.
4. Gỡ hai biến drill, redeploy Worker tốt. Sau khi lease 3 phút hết hạn, Worker lấy lại event. Đối chiếu ảnh nhỏ và lớn, một job COMPLETED, một dòng processed event, 100% progress và đủ nhật ký cùng request ID. Giữ cấu hình alert ban đầu sau diễn tập.

```sql
SELECT i.id, i.status, i.progress, j.id AS job_id, j.completed_at,
       e.status AS delivery, e.attempts,
       (SELECT count(*) FROM processed_events p WHERE p.image_id = i.id) AS terminal_events
FROM images i JOIN processing_jobs j ON j.image_id = i.id
JOIN outbox_events e ON e.aggregate_id = i.id
WHERE i.id = '<qa-photo-id>';
```

Mở dashboard `/ops/` trên API staging, nhập Ops token để dashboard làm mới mỗi 15 giây. Dùng endpoint `/api/metrics` cho tuổi job, độ trễ, tỷ lệ lỗi, số lần thử lại và dung lượng thumbnail đã ghi nhận. Thu đủ dữ liệu dashboard trong lần diễn tập và đối chiếu thời điểm Worker chết, webhook đến và Worker hoàn tất. Nếu Worker bị cạn retry, giữ bằng chứng event FAILED và tạo ảnh tổng hợp mới để lặp lại drill sau khi sửa nguyên nhân. Không đặt lại toàn bộ hàng đợi.
