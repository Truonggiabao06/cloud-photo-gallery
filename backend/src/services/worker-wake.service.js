let wakeInFlight;

function workerOrigin() {
  const url = new URL(process.env.WORKER_WAKE_URL || "");
  if ((url.protocol !== "https:" &&
       !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) ||
      url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("WORKER_WAKE_URL must be an HTTPS origin or a localhost test origin");
  }
  if ((process.env.WORKER_SHARED_SECRET || "").length < 32) {
    throw new Error("WORKER_SHARED_SECRET must be at least 32 characters");
  }
  return url.origin;
}

function wakeWorker() {
  if (process.env.STORAGE_BACKEND !== "s3" || wakeInFlight) return;
  wakeInFlight = fetch(`${workerOrigin()}/wake`, {
    method: "POST",
    headers: { "x-worker-secret": process.env.WORKER_SHARED_SECRET },
    signal: AbortSignal.timeout(90000),
    redirect: "error"
  }).then(response => {
    if (response.status !== 202) throw new Error("Wake endpoint returned an unexpected status");
  }).catch(() => {
    console.warn(JSON.stringify({ event: "worker_wake_failed" }));
  }).finally(() => {
    wakeInFlight = undefined;
  });
}

module.exports = { wakeWorker, workerOrigin };
