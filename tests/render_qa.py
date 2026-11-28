#!/usr/bin/env python3
"""Run acceptance against a dedicated Render/Supabase staging environment."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
from threading import local
from time import monotonic, sleep
from urllib.parse import urlsplit, urlunsplit

import boto3
from botocore.config import Config
from PIL import Image
import psycopg
import requests

from qa_suite import require, stamp, utc, percentile95


def fixtures():
    for index in range(105):
        png = index < 100 and index % 2 == 1
        extension = "png" if png else "jpg"
        if index < 100:
            image = Image.new("RGB", (1000, 750), (index, 82, 153))
            buffer = BytesIO()
            image.save(buffer, "PNG" if png else "JPEG")
            contents = buffer.getvalue()
            name = f"image_{index + 1:03d}.{extension}"
        else:
            name = f"error_{index + 1:03d}.jpg"
            contents = f"synthetic corrupt JPEG {index}\n".encode()
        yield name, contents, "image/png" if png else "image/jpeg", index < 100


class Stage:
    def __init__(self, roles):
        origin = urlsplit(os.environ["QA_API_URL"])
        require(origin.scheme == "https" and origin.hostname and not origin.username and
                origin.path in ("", "/") and not origin.query and not origin.fragment,
                "QA_API_URL must be the staging HTTPS origin")
        self.origin = origin.geturl().rstrip("/")
        self.tokens = {role: os.environ[f"QA_{role.upper()}_TOKEN"]
                       for role in roles}
        self.sessions = local()

    def http(self, method, url, **kwargs):
        if not hasattr(self.sessions, "http"):
            self.sessions.http = requests.Session()
            self.sessions.http.trust_env = False
        return self.sessions.http.request(method, url, timeout=(5, 30), allow_redirects=False, **kwargs)

    def api(self, method, path, role="owner", expected=200, **kwargs):
        token = self.tokens.get(role)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        result = self.http(method, self.origin + path, headers=headers, **kwargs)
        require(result.status_code == expected, f"{method} {path.split('?')[0]} ({role}) HTTP {result.status_code}")
        return result.json()

    def upload(self, album, name, contents, mime):
        result = self.api("POST", "/api/photos/upload", expected=201,
                          data={"albumId": album}, files={"image": (name, contents, mime)})
        require(result["queue"]["queued"], "Event was not committed to Outbox")
        return result["photo"]["id"]

    def private_objects(self, photo):
        for url in [photo["originalUrl"], *photo["thumbnailUrls"].values()]:
            parsed = urlsplit(url)
            require(parsed.scheme == "https" and bool(parsed.query), "Expected HTTPS signed URL")
            unsigned = urlunsplit(parsed._replace(query="", fragment=""))
            with self.http("GET", unsigned, stream=True) as denied:
                require(denied.status_code in (401, 403, 404), "Unsigned object was accessible")
            with self.http("GET", url, stream=True) as allowed:
                require(allowed.status_code == 200, "Signed object was inaccessible")


def list_keys(s3, bucket, photo_id):
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"thumbnails/{photo_id}/")
    return sorted(item["Key"] for page in pages for item in page.get("Contents", []))


def poll(probe, timeout):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        value = probe()
        if value:
            return value
        sleep(3)
    raise AssertionError("Timed out waiting for durable Worker progress")


def replay(db, photo_id, timeout):
    def snapshot():
        return db.execute("""
          SELECT i.status, j.id::text, j.completed_at::text,
            (SELECT count(*) FROM processed_events p WHERE p.image_id = i.id)
          FROM images i JOIN processing_jobs j ON j.image_id = i.id WHERE i.id = %s
        """, (photo_id,)).fetchone()

    before = snapshot()
    require(before and before[0] == "COMPLETED" and before[3] == 1, "Missing unique completion")
    for _ in range(5):
        poll(lambda: db.execute("""
          UPDATE outbox_events SET status = 'PENDING', available_at = now(), published_at = NULL
          WHERE id = %s AND event_type = 'PHOTO_UPLOADED' AND status = 'PUBLISHED'
          RETURNING id
        """, (photo_id,)).fetchone(), timeout)
        poll(lambda: db.execute("""
          SELECT 1 FROM outbox_events WHERE id = %s AND status = 'PUBLISHED'
        """, (photo_id,)).fetchone(), timeout)
        require(snapshot() == before, "Replay changed the terminal job")
    return {"additionalDeliveries": 5, "logicalImages": 1, "completedJobs": 1, "processedEvents": before[3]}


def acceptance(stage, args, report):
    identities = {role: stage.api("GET", "/api/auth/me", role)["user"]["id"] for role in stage.tokens}
    require(len(set(identities.values())) == len(identities), "Use distinct test identities")
    report["authorizationMode"] = "three-accounts" if "outsider" in identities else "before-and-after-invite"
    outsider = "outsider" if "outsider" in identities else "viewer"
    album = stage.api("POST", "/api/albums", expected=201, json={
        "name": "QA Render " + stamp(), "description": "Synthetic staging acceptance"
    })["album"]["_id"]
    report["albumId"] = album
    inputs = list(fixtures())
    report["inputs"] = [{"name": name, "sha256": hashlib.sha256(data).hexdigest(),
                         "expected": "COMPLETED" if valid else "FAILED"}
                        for name, data, _, valid in inputs]
    for record, (name, contents, mime, _) in zip(report["inputs"], inputs):
        record["photoId"] = stage.upload(album, name, contents, mime)

    def gallery():
        photos = stage.api("GET", f"/api/photos?albumId={album}")["photos"]
        if len(photos) == 105 and all(p["status"] in ("COMPLETED", "FAILED") for p in photos):
            return {p["originalName"]: p for p in photos}

    photos = poll(gallery, args.timeout)
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name=os.environ["S3_REGION"],
                      aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
                      config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                    connect_timeout=5, read_timeout=20))
    bucket = os.environ["S3_BUCKET"]
    for record in report["inputs"]:
        photo = photos[record["name"]]
        require(photo["_id"] == record["photoId"] and photo["status"] == record["expected"], "Unexpected terminal state")
        keys = list_keys(s3, bucket, photo["_id"])
        record["status"] = photo["status"]
        if photo["status"] == "COMPLETED":
            require(photo["progress"] == 100 and keys == sorted(
                f"thumbnails/{photo['_id']}/{label}.webp" for label in ("small", "large")),
                "Expected two derivative objects")
        else:
            require(bool(photo["errorMessage"]) and not keys, "Expected visible error and no derivatives")
        record["objects"] = keys
    counts = Counter(item["status"] for item in report["inputs"])
    report["test1"] = {"completed": counts["COMPLETED"], "objects": sum(len(item["objects"]) for item in report["inputs"])}
    target = photos[inputs[0][0]]
    photo_id = target["_id"]
    status_path = f"/api/photos/{photo_id}/status"
    gallery_path = f"/api/photos?albumId={album}"
    stage.api("GET", status_path, outsider, expected=404)
    require(not stage.api("GET", gallery_path, outsider)["photos"],
            "An uninvited account received gallery records")
    stage.api("GET", status_path, "anonymous", expected=401)

    stage.api("POST", f"/api/albums/{album}/members", json={"memberId": identities["viewer"]})
    stage.api("GET", status_path, "viewer")
    stage.api("POST", f"/api/albums/{album}/members", "viewer", expected=404,
              json={"memberId": identities["owner"]})
    stage.api("POST", "/api/photos/upload", "viewer", expected=404, data={"albumId": album},
              files={"image": (inputs[0][0], inputs[0][1], inputs[0][2])})
    if "outsider" in identities:
        stage.api("GET", status_path, "outsider", expected=404)
        require(not stage.api("GET", gallery_path, "outsider")["photos"],
                "An uninvited account received gallery records after sharing")
    stage.private_objects(target)
    report["test3"] = {"failed": counts["FAILED"], "ownerAndViewerAllowed": True,
                       "viewerWriteDenied": True, "outsiderAndUnsignedDenied": True}
    original_keys = list_keys(s3, bucket, photo_id)
    original_etags = [s3.head_object(Bucket=bucket, Key=key)["ETag"] for key in original_keys]
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, connect_timeout=10) as db:
        report["test2"] = replay(db, photo_id, 90)
    require(original_keys == list_keys(s3, bucket, photo_id) and original_etags == [
        s3.head_object(Bucket=bucket, Key=key)["ETag"] for key in original_keys], "Replay altered derivatives")
    report["samplePhotoId"] = photo_id


def load(stage, args, report):
    require(args.photo_id and 1 <= args.concurrency <= 10 and 1 <= args.rps <= 15 and
            1 <= args.duration <= 120 and 0 <= args.warmup <= 30, "Invalid bounded load parameters")
    path = f"/api/photos/{args.photo_id}/status"
    stage.api("GET", path)

    def sample():
        started = monotonic()
        try:
            status = stage.http("GET", stage.origin + path,
                                headers={"Authorization": f"Bearer {stage.tokens['owner']}"}).status_code
        except requests.RequestException:
            status = 0
        return status, round((monotonic() - started) * 1000, 2)

    def phase(seconds):
        interval = 1 / args.rps
        results = []
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            start = monotonic()
            for index in range(seconds * args.rps):
                sleep(max(0, start + index * interval - monotonic()))
                results.append(pool.submit(sample))
            return [future.result() for future in results]

    warm = phase(args.warmup)
    measured = phase(args.duration)
    success = sorted(ms for code, ms in measured if code == 200)
    report["load"] = {"endpoint": "GET /api/photos/:id/status", "photoId": args.photo_id,
                      "warmupSeconds": args.warmup, "durationSeconds": args.duration,
                      "concurrency": args.concurrency, "targetRps": args.rps,
                      "warmupRequests": len(warm), "requests": len(measured),
                      "httpStatuses": dict(Counter(code for code, _ in measured)),
                      "errorRate": 1 - len(success) / len(measured),
                      "p95Ms": percentile95(success) if success else None,
                      "samples": [{"status": code, "elapsedMs": ms} for code, ms in measured]}
    require(len(success) == len(measured), "Load test observed HTTP errors")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["acceptance", "load"])
    parser.add_argument("--two-accounts", action="store_true",
                        help="Check the viewer account before and after the invitation")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--photo-id")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--rps", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("evidence"))
    args = parser.parse_args()
    require(os.getenv("QA_CONFIRM_STAGING") == "yes", "Set QA_CONFIRM_STAGING=yes for a dedicated staging environment")
    require(1 <= args.timeout <= 1800, "Timeout must be between 1 and 1800 seconds")
    report = {"command": args.command, "startedAt": utc()}
    try:
        roles = ["owner"]
        if args.command == "acceptance":
            roles.append("viewer")
            if not args.two_accounts:
                roles.append("outsider")
            for key in ("DATABASE_URL", "S3_ENDPOINT", "S3_REGION", "S3_BUCKET",
                        "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
                require(os.getenv(key), f"Missing staging environment variable: {key}")
        stage = Stage(roles)
        (acceptance if args.command == "acceptance" else load)(stage, args, report)
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = type(exc).__name__
        # Only messages from local assertions are designed for export.
        if type(exc).__name__ in ("AssertionError", "CheckFailed"):
            report["check"] = str(exc)
    report["endedAt"] = utc()
    args.out.mkdir(parents=True, exist_ok=True)
    destination = args.out / f"render-{args.command}-{stamp()}.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(destination)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
