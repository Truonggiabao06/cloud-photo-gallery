# Giao diện của TV 1

Mẫu container này dự kiến dùng SPA Vite (React, Vue hoặc Vanilla). Đặt source, `package.json` và `package-lock.json` trong thư mục này. `npm run build` phải xuất `dist/`. Nếu dùng công cụ khác, điều chỉnh bước build và đường dẫn output trong Dockerfile. Nginx phục vụ SPA trên cổng 8080 và hỗ trợ tải lại route sâu.

| Biến build công khai | Nguồn |
| --- | --- |
| `VITE_API_BASE_URL` | Cloud Run URL của Backend |
| `VITE_ENTRA_TENANT_ID` | Directory ID của Entra |
| `VITE_ENTRA_CLIENT_ID` | App registration của SPA, khác API client ID |
| `VITE_ENTRA_API_SCOPE` | Delegated scope, mặc định `api://<API_APP_ID>/access_as_user` |

TV 1 đăng ký redirect URI loại SPA đúng với URL Cloud Run và callback mà app sử dụng. MSAL lấy access token cho API rồi gọi Backend với `Authorization: Bearer …`. Backend hiện nhận multipart `albumId` và `image` ở `POST /api/photos/upload`. Poll `GET /api/photos/:id/status` theo nhịp có giới hạn, dừng khi `COMPLETED` hoặc `FAILED`. Khi TV 2 thêm signed PUT và finalize, thêm luồng direct upload với header precondition đã ký. CORS cho origin chính được Terraform quản lý. Truy cập ảnh dùng signed URL nhận từ API. Giữ token trong cơ chế cache phù hợp của MSAL, tránh log URL signed, và tuyệt đối giữ `WORKER_SHARED_SECRET` ngoài bundle.
