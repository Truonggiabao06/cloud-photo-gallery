# Project 07 · TV 5 · Cloud Photo Gallery trên Google Cloud

Bắt đầu tại [hướng dẫn triển khai](docs/deploy_guide.md). Dùng một project staging có billing, một repo nhóm và hai tài khoản Entra demo thuộc cùng tenant. Khu vực mặc định là Singapore (`asia-southeast1`).

- [Rà soát tích hợp và việc cần chốt giữa các TV](docs/integration_audit.md)
- [Báo cáo thiết kế và sơ đồ](docs/design_report.md)
- [Monitoring, cảnh báo và phục hồi](docs/monitoring_runbook.md)
- [Chi phí và thu dọn](docs/cost_and_cleanup.md)
- [Kịch bản demo 12 phút](docs/demo_script_12min.md)

Nhánh tích hợp Render + Supabase dùng [hướng dẫn Terraform và GitHub Actions](docs/render-supabase-phase3.md).

`backend/` chứa bản hiện tại của TV 2, với mã ứng dụng giữ nguyên và bổ sung Dockerfile, lockfile và hai ngoại lệ Git cho manifest. `frontend/` và `worker/` chứa mẫu container và hướng dẫn tích hợp cho TV 1/3. `infra/` dựng hạ tầng và `tests/` chạy QA từ Cloud Shell. Trước khi TV 1/3 đưa code vào, Cloud Run dùng image bootstrap. Chỉ bật Pub/Sub push sau khi Worker thật đã lên.

Backend dùng Cloud SQL PostgreSQL 15 với schema thành viên 4 và migration tích hợp. Xem [cách chạy PostgreSQL](docs/postgresql.md) và chạy QA trên môi trường thực tế để lấy bằng chứng.
