#!/usr/bin/env python3
"""Cloud-only acceptance checks with synthetic fixtures and sanitized JSON evidence."""
import argparse
import concurrent.futures as futures
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import quote, urlsplit

from google.cloud import logging as cloud_logging
from google.cloud import pubsub_v1, storage
from PIL import Image
import requests


TERMINAL = {"COMPLETED", "FAILED"}
TIMEOUT = (5, 25)


class CheckFailed(Exception):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def fixture(index, invalid=False):
    if invalid:
        return f"fixture: invalid jpeg {index}\n".encode()
    width, height = 1000, 750
    img = Image.new("RGB", (width, height))
    img.paste((index, 80, 170), (0, 0, width, height))
    img.paste((205, index, 90), (40 + index, 20, 400, 300))
    buffer = io.BytesIO()
    img.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def dataset(path):
    path.mkdir(parents=True, exist_ok=True)
    manifest = []
    for kind, count in (("valid", 100), ("invalid", 5)):
        for index in range(count):
            name = f"{kind}-{index:03d}.jpg"
            contents = fixture(index, invalid=kind == "invalid")
            (path / name).write_bytes(contents)
            manifest.append({"name": name, "expected": kind, "sha256": hashlib.sha256(contents).hexdigest()})
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


class API:
    def __init__(self, url, owner, other=""):
        parsed = urlsplit(url)
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.query and not parsed.fragment and parsed.path in ("", "/"),
                "QA_API_URL must be an HTTPS origin")
        self.url = url.rstrip("/")
        self.tokens = {"owner": owner, "other": other}
        self.local = threading.local()

    def session(self):
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()
            # Keep netrc credentials and local HTTP proxies out of negative checks.
            self.local.session.trust_env = False
        return self.local.session

    def call(self, method, path, expected=(200,), actor="owner", **kwargs):
        headers = kwargs.pop("headers", {})
        if self.tokens.get(actor):
            headers = {**headers, "Authorization": f"Bearer {self.tokens[actor]}"}
        response = self.session().request(
            method, self.url + path, headers=headers, timeout=TIMEOUT, allow_redirects=False, **kwargs
        )
        require(response.status_code in expected,
                f"{method} {path.split('?')[0]} returned HTTP {response.status_code}, expected {list(expected)}")
        if response.status_code < 300 and "application/json" in response.headers.get("Content-Type", ""):
            result = response.json()
            require(result.get("success") is not False, f"{method} {path.split('?')[0]} reported failure")
            return result
        return response.status_code

    def album(self, label):
        return self.call("POST", "/api/albums", (201,), json={
            "name": f"QA {label} {stamp()}", "description": "Synthetic staging fixtures"
        })["album"]["_id"]

    def upload(self, album, name, content):
        result = self.call("POST", "/api/photos/upload", (201,), data={"albumId": album},
                           files={"image": (name, content, "image/jpeg")})
        queue = result["queue"]
        require(queue.get("queued") is True or queue.get("published") is True,
                "Backend did not accept the processing event")
        photo = result["photo"]
        return {"id": photo["id"], "name": name, "submittedAt": utc(),
                "initialStatus": photo["status"], "messageId": queue.get("messageId")}

    def list_photos(self, album):
        return self.call("GET", "/api/photos", params={"albumId": album})["photos"]

    def poll(self, photo_ids, timeout, interval):
        deadline = time.monotonic() + timeout
        remaining = list(photo_ids)
        seen = {}
        while remaining:
            for photo_id in remaining:
                status = self.call("GET", f"/api/photos/{photo_id}/status")
                require(status["photoId"] == photo_id, "API returned the wrong photo ID")
                seen[photo_id] = {
                    "status": status["status"], "progress": status["progress"],
                    "updatedAt": status.get("updatedAt"),
                    "errorReasonPresent": isinstance(status.get("errorMessage"), str)
                    and bool(status["errorMessage"].strip()),
                }
                if time.monotonic() >= deadline:
                    break
            remaining = [key for key in remaining if seen.get(key, {}).get("status") not in TERMINAL]
            if not remaining or time.monotonic() >= deadline:
                break
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
        return seen

    def check_unsigned(self, url, statuses):
        # A fresh session prevents bearer token, cookies or ADC reaching anonymous probes.
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True) as response:
                require(response.status_code in statuses, f"Object/protected endpoint returned HTTP {response.status_code}")
                return response.status_code


def object_url(bucket, key):
    return f"https://storage.googleapis.com/{bucket}/{quote(key, safe='/')}"


def derivative_keys(prefix, photo_id):
    return {f"{prefix}{photo_id}/{variant}.webp" for variant in ("small", "large")}


def derivatives(client, bucket, prefix, photo_id):
    result = {}
    for blob in client.list_blobs(bucket, prefix=f"{prefix}{photo_id}/", timeout=20):
        result[blob.name] = {"generation": str(blob.generation), "size": blob.size}
    return result


def completed_status(states, ids):
    return all(states.get(key, {}).get("status") == "COMPLETED"
               and states[key]["progress"] == 100 for key in ids)


def replay(api, args, gallery, google_storage, report):
    row = gallery[0]
    photo_id = row["_id"]
    initial = derivatives(google_storage, args.bucket, args.prefix, photo_id)
    album_before = api.call("GET", f"/api/albums/{row['albumId']}")["album"]["photoCount"]
    event = {
        "eventType": "PHOTO_UPLOADED", "eventVersion": 1, "photoId": photo_id,
        "albumId": str(row["albumId"]), "userId": row["ownerId"], "bucket": args.bucket,
        "originalObject": row["originalObject"], "mimeType": row["mimeType"],
        "createdAt": row["createdAt"],
    }
    publisher = pubsub_v1.PublisherClient()
    topic = publisher.topic_path(args.project, args.topic)
    data = json.dumps(event, separators=(",", ":")).encode()
    pending = [publisher.publish(topic, data, eventType=event["eventType"], photoId=photo_id)
               for _ in range(5)]
    message_ids = [item.result(timeout=30) for item in pending]
    report.update({"photoId": photo_id, "messageIds": message_ids, "payloadSha256": hashlib.sha256(data).hexdigest()})

    # Require proof that all five deliveries finished. A fixed sleep can falsely pass an idle Worker.
    logging = cloud_logging.Client(project=args.project)
    service = args.worker_service
    filter_query = (
        f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" '
        f'AND jsonPayload.photoId="{photo_id}" AND '
        '(jsonPayload.event="delivery_ack" OR jsonPayload.event="job_terminal")'
    )
    deadline = time.monotonic() + args.replay_timeout
    acknowledged = set()
    commits = []
    while True:
        entries = list(logging.list_entries(filter_=filter_query, max_results=100, page_size=100))
        acknowledged = {entry.payload.get("messageId") for entry in entries
                        if entry.payload.get("event") == "delivery_ack"}
        commits = [entry.payload for entry in entries if entry.payload.get("event") == "job_terminal"]
        report["acknowledgedReplayIds"] = sorted(set(message_ids) & acknowledged)
        report["terminalCommitLogCount"] = len(commits)
        if set(message_ids) <= acknowledged and commits:
            break
        require(time.monotonic() < deadline, "Replay ACK or terminal logs missing; inspect Worker and Logging")
        time.sleep(5)

    after = derivatives(google_storage, args.bucket, args.prefix, photo_id)
    report["derivativeGenerationsBefore"] = {key: item["generation"] for key, item in initial.items()}
    report["derivativeGenerationsAfter"] = {key: item["generation"] for key, item in after.items()}
    require(set(initial) == set(after) == derivative_keys(args.prefix, photo_id),
            "Replay did not preserve exactly two logical derivatives")
    require(len(commits) == 1 and commits[0].get("status") == "COMPLETED" and commits[0].get("jobId"),
            "Expected exactly one successful terminal commit with jobId in Worker logs")
    album_after = api.call("GET", f"/api/albums/{row['albumId']}")["album"]["photoCount"]
    matching = [item for item in api.list_photos(row["albumId"]) if item["_id"] == photo_id]
    require(len(matching) == 1 and album_after == album_before, "Replay changed logical photo count")
    require(completed_status(api.poll([photo_id], 3, 1), [photo_id]), "Replay changed the terminal status")


def security(api, args, album, valid, derivative_set, report):
    first_id = valid["_id"]
    photo_path = f"/api/photos/{first_id}"
    require(api.call("GET", "/api/auth/me")["user"]["id"] !=
            api.call("GET", "/api/auth/me", actor="other")["user"]["id"],
            "Supply two distinct Entra test users")
    for route in ("/api/auth/me", "/api/albums", f"/api/albums/{album}",
                  "/api/photos", f"{photo_path}/status"):
        report[f"anonymous {route}"] = api.call("GET", route, (401,), actor="anonymous")
    report["anonymous create album"] = api.call(
        "POST", "/api/albums", (401,), actor="anonymous", json={"name": "QA anonymous"}
    )
    report["anonymous upload"] = api.call(
        "POST", "/api/photos/upload", (401,), actor="anonymous",
        data={"albumId": album}, files={"image": ("denied.jpg", fixture(0), "image/jpeg")}
    )
    report["cross-user album"] = api.call("GET", f"/api/albums/{album}", (403, 404), actor="other")
    report["cross-user status"] = api.call("GET", f"{photo_path}/status", (403, 404), actor="other")
    report["cross-user upload"] = api.call(
        "POST", "/api/photos/upload", (403, 404), actor="other",
        data={"albumId": album}, files={"image": ("denied.jpg", fixture(0), "image/jpeg")}
    )
    other_listing = api.call("GET", "/api/photos", (200, 403, 404), actor="other", params={"albumId": album})
    if isinstance(other_listing, dict):
        require(not other_listing["photos"], "An unauthorized user can list album photos")
    report["cross-user listing"] = 200 if isinstance(other_listing, dict) else other_listing
    report["invalid worker secret"] = api.call(
        "PATCH", f"{photo_path}/worker-status", (401, 403), actor="anonymous",
        headers={"x-worker-secret": "qa-deliberately-invalid"}, json={"status": "COMPLETED", "progress": 100}
    )
    report["private Cloud Run Worker"] = api.check_unsigned(args.worker_url.rstrip("/") + args.worker_path, (401, 403, 404))
    report["owner signed original"] = api.check_unsigned(valid["originalUrl"], (200,))
    for url in [valid.get("thumbnailUrl")] + list((valid.get("thumbnailUrls") or {}).values()
                                                  if isinstance(valid.get("thumbnailUrls"), dict) else []):
        if url:
            api.check_unsigned(url, (200,))
    original = valid["originalObject"]
    report["unsigned original"] = api.check_unsigned(object_url(args.bucket, original), (403,))
    report["unsigned derivatives"] = {
        key: api.check_unsigned(object_url(args.bucket, key), (403,)) for key in sorted(derivative_set)
    }

    member_id = api.call("GET", "/api/auth/me", actor="other")["user"]["id"]
    invitation = api.call("POST", f"/api/albums/{album}/members", json={"memberId": member_id})
    require(invitation["member"]["role"] == "VIEWER", "Expected a viewer invitation")
    report["invited viewer album"] = api.call("GET", f"/api/albums/{album}", actor="other")["album"]["_id"]
    viewer_photos = api.call("GET", "/api/photos", actor="other", params={"albumId": album})["photos"]
    require(any(row["_id"] == valid["_id"] for row in viewer_photos), "Viewer cannot list shared photos")
    report["invited viewer status"] = api.call("GET", f"{photo_path}/status", actor="other")["status"]
    report["invited viewer upload"] = api.call(
        "POST", "/api/photos/upload", (403, 404), actor="other",
        data={"albumId": album}, files={"image": ("denied.jpg", fixture(0), "image/jpeg")}
    )


def stage(report, name, operation):
    block = {"startedAt": utc(), "passed": False}
    report["checks"][name] = block
    try:
        operation(block)
        block["passed"] = True
    except CheckFailed as error:
        block["failure"] = str(error)
    except Exception as error:
        # Third-party exceptions can include a signed URL or private response body.
        block["failure"] = type(error).__name__
    block["finishedAt"] = utc()
    print(f"{'PASS' if block['passed'] else 'FAIL'} {name}", flush=True)


def run_suite(api, args, report):
    google_storage = storage.Client(project=args.project)
    client_bucket = google_storage.bucket(args.bucket)
    manifest = dataset(args.out / f"{report['runId']}-fixtures")
    fixtures = args.out / f"{report['runId']}-fixtures"
    report["dataset"] = manifest
    results = {}

    def check_warm(block):
        for route in ("/", "/api/health", "/api/auth/me", "/api/albums"):
            api.call("GET", route, actor="owner")
        api.call("GET", "/api-docs/", actor="anonymous")
        bucket = google_storage.get_bucket(args.bucket) if args.check_bucket_iam else None
        if bucket is not None:
            require(bucket.iam_configuration.public_access_prevention == "enforced", "GCS PAP is not enforced")
            require(bucket.iam_configuration.uniform_bucket_level_access_enabled, "GCS UBLA is disabled")
            block["bucketConfigurationVerified"] = True

    def submit(kind, block):
        album = api.album(kind)
        block["albumId"] = album
        uploads = []
        block["uploads"] = uploads
        for item in manifest:
            if item["expected"] != kind:
                continue
            name = item["name"]
            uploads.append(api.upload(album, name, (fixtures / name).read_bytes()))
        ids = [item["id"] for item in uploads]
        block["photos"] = api.poll(ids, args.timeout, args.poll)
        photo_count = api.call("GET", f"/api/albums/{album}")["album"]["photoCount"]
        gallery = api.list_photos(album)
        require(photo_count == len(ids) and {row["_id"] for row in gallery} == set(ids)
                and len(gallery) == len(ids), "Album and gallery row counts do not match the isolated dataset")
        results[kind] = gallery
        return ids, gallery

    def valid(block):
        ids, gallery = submit("valid", block)
        counts = {}
        block["derivativeCounts"] = counts
        bad = []
        for row in gallery:
            photo_id = row["_id"]
            files = derivatives(google_storage, args.bucket, args.prefix, photo_id)
            counts[photo_id] = len(files)
            if set(files) != derivative_keys(args.prefix, photo_id) or any(item["size"] <= 0 for item in files.values()):
                bad.append(photo_id)
        block["thumbnailCount"] = sum(counts.values())
        block["readyRecords"] = sum(completed_status(block["photos"], [photo_id]) for photo_id in ids)
        block["derivativeContractViolations"] = bad
        if not bad:
            for photo_id in ids:
                sizes = {}
                for variant in ("small", "large"):
                    key = f"{args.prefix}{photo_id}/{variant}.webp"
                    content = client_bucket.blob(key).download_as_bytes(timeout=20)
                    with Image.open(io.BytesIO(content)) as thumbnail:
                        thumbnail.load()
                        require(thumbnail.format == "WEBP", "Derivative must be a decodable WebP")
                        sizes[variant] = max(thumbnail.size)
                if sizes != {"small": args.small_size, "large": args.large_size}:
                    bad.append(photo_id)
        require(len(ids) == 100 and block["readyRecords"] == 100 and block["thumbnailCount"] == 200 and not bad,
                "Expected 100 COMPLETED at 100% and exactly 200 nonempty deterministic derivatives")

    def invalid(block):
        ids, gallery = submit("invalid", block)
        block["storage"] = {}
        for row in gallery:
            photo_id, key = row["_id"], row["originalObject"]
            require(client_bucket.blob(key).exists(timeout=20), "Invalid fixture original missing from private storage")
            present = derivatives(google_storage, args.bucket, args.prefix, photo_id)
            block["storage"][photo_id] = {
                "originalUnsignedHttp": api.check_unsigned(object_url(args.bucket, key), (403,)),
                "derivativeUnsignedHttp": {
                    name: api.check_unsigned(object_url(args.bucket, name), (403,))
                    for name in sorted(set(present) | derivative_keys(args.prefix, photo_id))
                },
                "liveDerivativeCount": len(present),
            }
        require(len(ids) == 5 and all(block["photos"].get(key, {}).get("status") == "FAILED"
                and block["photos"][key]["errorReasonPresent"] for key in ids),
                "Expected five visible FAILED states with a readable failure reason")

    def pick_valid():
        gallery = results.get("valid")
        require(gallery, "Test 1 has no usable gallery records")
        return gallery

    stage(report, "smoke", check_warm)
    stage(report, "test1", valid)

    def check_security(block):
        row = pick_valid()[0]
        present = set(derivatives(google_storage, args.bucket, args.prefix, row["_id"]))
        if row.get("thumbnailObject"):
            present.add(row["thumbnailObject"])
        security(api, args, row["albumId"], row, present, block)
        require(present, "No derivative available for a real anonymous denial check")

    stage(report, "security", check_security)
    stage(report, "test2", lambda block: replay(api, args, pick_valid(), google_storage, block))
    stage(report, "test3", invalid)
    return all(item["passed"] for item in report["checks"].values())


def percentile95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None


def load(api, args, report):
    source = json.loads(args.from_run.read_text())
    expected = source["checks"]["test1"]
    require(expected["passed"], "Load dataset requires a passing Test 1")
    ids = [item["id"] for item in expected["uploads"]]
    report["parameters"] = {
        "endpoint": "GET /api/photos/:id/status", "warmupSeconds": args.warmup,
        "durationSeconds": args.duration, "concurrency": args.concurrency, "targetRps": args.rps,
        "datasetCount": len(ids), "datasetRunId": source["runId"], "datasetPhotoIds": ids,
        "p95Method": "nearest rank over successful measured HTTP responses in milliseconds",
    }
    semaphore = threading.BoundedSemaphore(args.concurrency)
    records = []

    def request(index, photo_id):
        start = time.perf_counter()
        record = {"index": index, "photoId": photo_id, "timestamp": utc()}
        try:
            with api.session().get(
                api.url + f"/api/photos/{photo_id}/status",
                headers={"Authorization": f"Bearer {api.tokens['owner']}"},
                timeout=TIMEOUT, allow_redirects=False,
            ) as response:
                record["httpStatus"] = response.status_code
                record["ok"] = response.status_code == 200
                if record["ok"]:
                    record["ok"] = response.json().get("photoId") == photo_id
        except (requests.RequestException, ValueError) as error:
            record.update({"ok": False, "error": type(error).__name__})
        finally:
            record["latencyMs"] = round((time.perf_counter() - start) * 1000, 3)
            semaphore.release()
        return record

    def phase(seconds):
        if not seconds:
            return []
        tasks, dropped = [], []
        begin = time.monotonic()
        with futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for index in range(math.ceil(seconds * args.rps)):
                due = begin + index / args.rps
                if due >= begin + seconds:
                    break
                time.sleep(max(0, due - time.monotonic()))
                photo_id = ids[index % len(ids)]
                if time.monotonic() >= begin + seconds or not semaphore.acquire(blocking=False):
                    dropped.append({"index": index, "photoId": photo_id, "timestamp": utc(),
                                    "ok": False, "error": "client_capacity_or_schedule_drop"})
                    continue
                tasks.append(pool.submit(request, index, photo_id))
            time.sleep(max(0, begin + seconds - time.monotonic()))
        return sorted([task.result() for task in tasks] + dropped, key=lambda record: record["index"])

    report["warmup"] = phase(args.warmup)
    records = phase(args.duration)
    passed = [record["latencyMs"] for record in records if record["ok"]]
    submitted = sum("latencyMs" in record for record in records)
    http_errors = submitted - len(passed)
    report["summary"] = {
        "scheduledRequests": len(records), "sentRequests": submitted, "successfulRequests": len(passed),
        "clientDrops": len(records) - submitted, "httpOrTransportErrors": http_errors,
        "actualSentRps": submitted / args.duration, "httpOrTransportErrorRate": http_errors / max(1, submitted),
        "scheduledErrorRate": (len(records) - len(passed)) / max(1, len(records)),
        "p95Ms": percentile95(passed), "p95AllSentMs": percentile95([
            row["latencyMs"] for row in records if "latencyMs" in row
        ]),
    }
    report["measurements"] = records
    return len(records) > 0 and len(passed) == len(records)


def entrypoint():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("evidence"))
    subs = parser.add_subparsers(dest="mode", required=True)
    suite = subs.add_parser("run")
    suite.add_argument("--project", default=os.getenv("QA_PROJECT"))
    suite.add_argument("--bucket", default=os.getenv("QA_BUCKET"))
    suite.add_argument("--topic", default=os.getenv("QA_TOPIC"))
    suite.add_argument("--prefix", default=os.getenv("QA_DERIVATIVE_PREFIX", "thumbnails/"))
    suite.add_argument("--worker-service", default=os.getenv("QA_WORKER_SERVICE"))
    suite.add_argument("--worker-url", default=os.getenv("QA_WORKER_URL"))
    suite.add_argument("--worker-path", default="/pubsub/push")
    suite.add_argument("--timeout", type=int, default=300)
    suite.add_argument("--poll", type=int, default=5)
    suite.add_argument("--replay-timeout", type=int, default=180)
    suite.add_argument("--small-size", type=int, default=200)
    suite.add_argument("--large-size", type=int, default=800)
    suite.add_argument("--check-bucket-iam", action="store_true")
    perf = subs.add_parser("load")
    perf.add_argument("--from-run", type=Path, required=True)
    perf.add_argument("--duration", type=int, default=30)
    perf.add_argument("--warmup", type=int, default=5)
    perf.add_argument("--concurrency", type=int, default=4)
    perf.add_argument("--rps", type=float, default=2)
    subs.add_parser("fixtures")
    drill = subs.add_parser("drill")
    drill.add_argument("--photo-id")
    drill.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    report = {"runId": run_id, "mode": args.mode, "startedAt": utc(), "checks": {}}
    passed = False
    try:
        if args.mode == "fixtures":
            report["dataset"] = dataset(args.out / f"{run_id}-fixtures")
            passed = True
        else:
            owner = os.getenv("QA_OWNER_TOKEN", "")
            require(owner, "Set QA_OWNER_TOKEN to an Entra delegated API access token")
            api = API(os.environ["QA_API_URL"], owner, os.getenv("QA_OTHER_TOKEN", ""))
            if args.mode == "run":
                require(all([api.tokens["other"], args.project, args.bucket, args.topic, args.worker_service,
                             args.worker_url]), "Set all QA_* settings listed in the deploy guide")
                require(args.worker_url.startswith("https://") and args.worker_path.startswith("/")
                        and args.prefix.endswith("/") and min(args.timeout, args.poll, args.replay_timeout) > 0
                        and 0 < args.small_size < args.large_size <= 1000,
                        "Invalid Worker URL/path, derivative prefix or timeout")
                passed = run_suite(api, args, report)
            elif args.mode == "load":
                require(args.duration > 0 and args.warmup >= 0 and args.concurrency > 0 and
                        math.isfinite(args.rps) and args.rps > 0, "Invalid load settings")
                passed = load(api, args, report)
            elif args.photo_id:
                report["photoId"] = args.photo_id
                report["status"] = api.poll([args.photo_id], args.timeout, 5)
                passed = completed_status(report["status"], [args.photo_id])
            else:
                album = api.album("crash-drill")
                report["albumId"] = album
                report["upload"] = api.upload(album, "drill.jpg", fixture(0))
                print(report["upload"]["id"], flush=True)
                passed = True
    except CheckFailed as error:
        report["failure"] = str(error)
    except Exception as error:
        report["failure"] = type(error).__name__
    report.update({"passed": passed, "finishedAt": utc()})
    path = args.out / f"{run_id}-{args.mode}.json"
    with path.open("x") as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write("\n")
    print(path, flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(entrypoint())
