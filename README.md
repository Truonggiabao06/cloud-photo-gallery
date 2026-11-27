# Project 07 · TV 5 · Cloud Photo Gallery trên Google Cloud

Bắt đầu tại [hướng dẫn triển khai](docs/deploy_guide.md). Dùng một project staging có billing, một repo nhóm và hai tài khoản Entra demo thuộc cùng tenant. Khu vực mặc định là Singapore (`asia-southeast1`).

- [Rà soát tích hợp và việc cần chốt giữa các TV](docs/integration_audit.md)
- [Báo cáo thiết kế và sơ đồ](docs/design_report.md)
- [Monitoring, cảnh báo và phục hồi](docs/monitoring_runbook.md)
- [Chi phí và thu dọn](docs/cost_and_cleanup.md)
- [Kịch bản demo 12 phút](docs/demo_script_12min.md)

`backend/` chứa bản hiện tại của TV 2, với mã ứng dụng giữ nguyên và bổ sung Dockerfile, lockfile và hai ngoại lệ Git cho manifest. `frontend/` và `worker/` chứa mẫu container và hướng dẫn tích hợp cho TV 1/3. `infra/` dựng hạ tầng và `tests/` chạy QA từ Cloud Shell. Trước khi TV 1/3 đưa code vào, Cloud Run dùng image bootstrap. Chỉ bật Pub/Sub push sau khi Worker thật đã lên.

Mốc nghiệm thu cần TV 1–4 hoàn thiện giao diện, quyền invited viewer, hai thumbnail, Outbox, sổ dedup và log Worker. Bản MongoDB của TV 2 phục vụ smoke test. Cloud SQL PostgreSQL 15 là tuỳ chọn hạ tầng và cần bản ứng dụng đã chuyển driver/schema trước khi sử dụng. Chạy QA trên bản tích hợp và nộp kết quả sinh từ lần chạy thật.
