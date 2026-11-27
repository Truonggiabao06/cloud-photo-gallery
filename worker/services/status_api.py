"""Authenticated client for Member 2's existing worker-status endpoint."""
from __future__ import annotations

import requests
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Settings


class WorkerStatusClient:
    def __init__(self, settings: Settings, *, session: requests.Session | None = None, lease_id: str | None = None) -> None:
        self.base_url = settings.api_base_url
        self.timeout = settings.api_timeout_seconds
        self.session = session or requests.Session()
        self._session_lock = threading.Lock()
        if lease_id:
            self.session.headers["x-outbox-lease"] = lease_id

        retry = Retry(
            total=3,
            connect=3,
            read=2,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"PATCH"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "x-worker-secret": settings.worker_shared_secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def update(self, photo_id: str, payload: dict) -> dict:
        """PATCH /api/photos/:id/worker-status; raises on any non-2xx response."""
        url = f"{self.base_url}/api/photos/{photo_id}/worker-status"
        # requests.Session is not guaranteed to be thread-safe. Serialize access
        # when MAX_MESSAGES is increased above the conservative default of 1.
        with self._session_lock:
            response = self.session.patch(
                url,
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
        if not 200 <= response.status_code < 300:
            # Do not follow redirects: a redirect must never receive the shared secret.
            # Avoid dumping request headers/secrets into logs.
            body = (response.text or "")[:300]
            raise RuntimeError(
                f"Backend worker-status API returned HTTP {response.status_code}: {body}"
            )

        if not response.text:
            return {}
        try:
            result = response.json()
        except ValueError:
            return {}
        return result if isinstance(result, dict) else {}
