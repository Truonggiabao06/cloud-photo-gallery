function numberSetting(env, name, fallback, min, max, integer = false) {
  const value = env[name] ? Number(env[name]) : fallback;
  if (!Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) {
    throw new Error(`Invalid ${name}`);
  }
  return value;
}

function loadAlertConfig(env = process.env) {
  if (!env.OPS_ALERT_WEBHOOK_URL) return null;
  const url = new URL(env.OPS_ALERT_WEBHOOK_URL);
  if (url.protocol !== "https:" || url.username || url.password || url.hash) {
    throw new Error("OPS_ALERT_WEBHOOK_URL must use HTTPS");
  }
  const format = env.OPS_ALERT_WEBHOOK_FORMAT || "json";
  if (!["json", "discord", "slack"].includes(format)) {
    throw new Error("OPS_ALERT_WEBHOOK_FORMAT must be json, discord or slack");
  }
  return {
    url, format,
    oldest: numberSetting(env, "OPS_OLDEST_JOB_SECONDS", 300, 60, 86400, true),
    failure: numberSetting(env, "OPS_FAILURE_RATE_THRESHOLD", 0.20, 0.01, 1),
    minJobs: numberSetting(env, "OPS_MIN_TERMINAL_JOBS", 5, 1, 1000, true),
    cooldown: numberSetting(env, "OPS_ALERT_COOLDOWN_SECONDS", 900, 60, 86400, true)
  };
}

function createAlertCheck(config, { readMetrics, send = fetch, now = Date.now }) {
  const sent = new Map();
  let checking = false;
  return async function check() {
    if (checking) return;
    checking = true;
    try {
      const metrics = await readMetrics();
      const active = [];
      if (metrics.oldestPendingJobAgeSeconds >= config.oldest) {
        active.push(["oldest-job", "Check Worker /health, Outbox leases and storage connectivity."]);
      } else {
        sent.delete("oldest-job");
      }
      if (metrics.terminalJobs >= config.minJobs && metrics.failureRate >= config.failure) {
        active.push(["failure-rate", "Check recent FAILED jobs and Worker storage or decoder errors."]);
      } else {
        sent.delete("failure-rate");
      }
      for (const [kind, action] of active) {
        if (now() - (sent.get(kind) ?? -Infinity) < config.cooldown * 1000) continue;
        const message = `Photo Gallery ${kind}. ${action}`;
        const payload = config.format === "discord" ? { content: message, allowed_mentions: { parse: [] } }
          : config.format === "slack" ? { text: message }
            : { event: "ops_alert", condition: kind, action, metrics };
        try {
          const response = await send(config.url, {
            method: "POST", redirect: "error", signal: AbortSignal.timeout(5000),
            headers: { "content-type": "application/json" }, body: JSON.stringify(payload)
          });
          await response.body?.cancel();
          if (!response.ok) throw new Error("Webhook rejected alert");
          sent.set(kind, now());
        } catch {
          console.warn(JSON.stringify({ event: "ops_alert_delivery_failed", condition: kind }));
        }
      }
    } catch {
      console.warn(JSON.stringify({ event: "ops_metrics_query_failed" }));
    } finally {
      checking = false;
    }
  };
}

module.exports = { loadAlertConfig, createAlertCheck };
