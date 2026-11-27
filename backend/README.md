# Cloud Photo Gallery Backend (Member 2)

## Stack
- Node.js + Express
- PostgreSQL 15
- Google Cloud Storage
- Google Pub/Sub
- Microsoft Entra ID access-token validation
- Swagger UI

## 1. Install
```bash
npm install
```

Copy `.env.example` to `.env`, then fill in real values. Never commit `.env` or service-account JSON.

## 2. Google Cloud setup
1. Select/create a GCP project.
2. Enable Cloud Storage and Pub/Sub APIs.
3. Create a private Cloud Storage bucket.
4. Create a service account and grant `Storage Object Admin` on the bucket and `Pub/Sub Publisher` on the topic.
5. Create a Pub/Sub topic, e.g. `photo-processing`.
6. For local development, set `GOOGLE_APPLICATION_CREDENTIALS` to the absolute path of the service-account JSON. On deployed Google Cloud services, prefer an attached service account / Application Default Credentials rather than a downloaded key.
7. Set `GCP_PROJECT_ID`, `GCS_BUCKET_NAME`, and `PUBSUB_TOPIC`.

## 3. Microsoft Entra setup
Register a Web API application in Entra:
1. Record Directory (tenant) ID and the API application's Application (client) ID.
2. Under **Expose an API**, set the Application ID URI and add a delegated scope such as `access_as_user`.
3. Configure the frontend app to request an access token for this API scope, e.g. `api://<API_CLIENT_ID>/access_as_user`.
4. Set `ENTRA_TENANT_ID`, `ENTRA_API_CLIENT_ID`, and `ENTRA_AUDIENCE` to the API app's client ID for a v2 token.
5. Optional: set `REQUIRED_API_SCOPE=access_as_user`.
6. The frontend signs in using MSAL and sends the **API access token** in `Authorization: Bearer <token>`. Do not send an ID token or a Microsoft Graph token.

This backend validates v2.0 tenant-specific tokens. If your Entra registration issues v1.0 tokens, configure the matching v1 metadata issuer/JWKS instead; do not simply disable issuer validation.

## 4. PostgreSQL
Apply the schema and migration in the [PostgreSQL guide](../docs/postgresql.md), then set `DATABASE_URL` in `.env`. URL-encode special characters in the database password.

## 5. Run
```bash
npm run dev
```
- API: http://localhost:3000
- Health: http://localhost:3000/api/health
- Swagger: http://localhost:3000/api-docs

## 6. API routes
| Method | Route | Auth |
|---|---|---|
| GET | `/api/health` | No |
| GET | `/api/auth/me` | Entra Bearer token |
| POST | `/api/albums` | Entra Bearer token |
| GET | `/api/albums` | Entra Bearer token |
| GET | `/api/albums/:id` | Entra Bearer token |
| POST | `/api/albums/:id/members` | Album owner |
| POST | `/api/photos/upload` | Entra Bearer token |
| GET | `/api/photos` | Entra Bearer token |
| GET | `/api/photos/:id/status` | Entra Bearer token |
| PATCH | `/api/photos/:id/worker-status` | `x-worker-secret` |

## 7. Postman test order
1. `GET http://localhost:3000/api/health`
2. Obtain a real **access token for this API** from the frontend/MSAL or your Entra test client.
3. In Postman, set Authorization > Bearer Token to that access token.
4. `GET http://localhost:3000/api/auth/me`
5. `POST http://localhost:3000/api/albums` with JSON:
```json
{ "name": "Da Lat Trip", "description": "Photos from the trip" }
```
6. Copy returned `album._id`.
7. `POST http://localhost:3000/api/photos/upload` as `form-data`:
   - key `albumId` (Text): the album ID
   - key `image` (File): choose a JPEG, PNG or WEBP image
8. Copy returned `photo.id`.
9. `GET http://localhost:3000/api/photos`
10. `GET http://localhost:3000/api/photos/<PHOTO_ID>/status`
11. `GET http://localhost:3000/api-docs` for interactive Swagger docs.

## 8. Worker contract (Member 3)
Pub/Sub message data is JSON:
```json
{
  "eventType": "PHOTO_UPLOADED",
  "eventVersion": 1,
  "photoId": "PostgreSQL photo UUID",
  "jobId": "PostgreSQL job UUID",
  "albumId": "PostgreSQL album UUID",
  "userId": "Entra subject",
  "bucket": "GCS bucket",
  "originalObject": "original/<user>/<album>/<uuid>.jpg",
  "mimeType": "image/jpeg",
  "createdAt": "ISO timestamp"
}
```
After processing, Worker calls:
`PATCH /api/photos/<PHOTO_ID>/worker-status`
with header `x-worker-secret: <WORKER_SHARED_SECRET>` and JSON such as:
```json
{ "status": "PROCESSING", "progress": 50 }
```
When done:
```json
{
  "status": "COMPLETED",
  "progress": 100,
  "thumbnailSmallObject": "thumbnails/<photo-id>/small.webp",
  "thumbnailLargeObject": "thumbnails/<photo-id>/large.webp"
}
```
On failure:
```json
{ "status": "FAILED", "errorMessage": "Reason" }
```
Worker should be idempotent because Pub/Sub delivery is at-least-once. It must acknowledge a message only after its work/status update is safely completed.

## Notes
- Upload limit is 10 MB; accepted formats are JPEG, PNG and WEBP.
- GCS bucket should remain private. API returns signed read URLs valid for 15 minutes.
- `PUBSUB_TOPIC` may be omitted for a local API-only smoke test; when set, the service account must have Pub/Sub Publisher. For the full assignment, configure Pub/Sub.
- This sample implements owner-only album/photo access. Add album member/share permissions if those are explicitly required.
- Production hardening should include a durable outbox/retry mechanism for Pub/Sub publishing, malware/content validation, stricter per-user quotas, audit logs, and managed secrets.
