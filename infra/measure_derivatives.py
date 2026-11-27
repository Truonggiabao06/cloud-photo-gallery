"""Cloud Run Job entry point. Lists derivative bytes and writes a gauge."""
import datetime as dt
import json
import os
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def call(url, headers, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    with urlopen(Request(url, data=data, headers=headers), timeout=20) as response:
        body = response.read()
        return json.loads(body) if body else {}


def main():
    project = os.environ["PROJECT_ID"]
    bucket = os.environ["GCS_BUCKET_NAME"]
    prefix = os.environ["DERIVATIVE_PREFIX"]
    token = call(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        {"Metadata-Flavor": "Google"},
    )["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    base = f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o"
    params = {"prefix": prefix, "fields": "items(size),nextPageToken", "maxResults": 1000}
    size = 0
    while True:
        page = call(f"{base}?{urlencode(params)}", headers)
        size += sum(int(item["size"]) for item in page.get("items", []))
        if "nextPageToken" not in page:
            break
        params["pageToken"] = page["nextPageToken"]
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {"timeSeries": [{
        "metric": {
            "type": os.environ["METRIC_TYPE"],
            "labels": {"bucket": bucket},
        },
        "resource": {"type": "global", "labels": {"project_id": project}},
        "points": [{"interval": {"endTime": now}, "value": {"int64Value": str(size)}}],
    }]}
    call(f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries", headers, payload)
    print(json.dumps({"event": "derivative_storage_sample", "sizeBytes": size}))


if __name__ == "__main__":
    main()
