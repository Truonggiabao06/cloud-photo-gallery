const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadAlertConfig, createAlertCheck } = require("../src/services/ops-alerts.service");

test("validates webhook URL and disables alerts with no webhook", () => {
  assert.equal(loadAlertConfig({}), null);
  assert.throws(() => loadAlertConfig({ OPS_ALERT_WEBHOOK_URL: "http://example.org" }), /HTTPS/);
  assert.throws(() => loadAlertConfig({
    OPS_ALERT_WEBHOOK_URL: "https://example.org", OPS_FAILURE_RATE_THRESHOLD: "101"
  }), /OPS_FAILURE_RATE_THRESHOLD/);
});

test("sends threshold alerts, respects cooldown and reopens alerts after recovery", async () => {
  const config = loadAlertConfig({ OPS_ALERT_WEBHOOK_URL: "https://example.org" });
  let clock = 0;
  let metrics = { oldestPendingJobAgeSeconds: 301, terminalJobs: 4, failureRate: 0.5 };
  const alerts = [];
  const check = createAlertCheck(config, {
    readMetrics: async () => metrics, now: () => clock,
    send: async (_url, options) => {
      alerts.push(JSON.parse(options.body).condition);
      return { ok: true };
    }
  });

  await check();
  metrics = { ...metrics, terminalJobs: 5 };
  await check();
  await check();
  assert.deepEqual(alerts, ["oldest-job", "failure-rate"]);
  clock += 901000;
  await check();
  assert.equal(alerts.length, 4);
  metrics = { ...metrics, failureRate: 0, oldestPendingJobAgeSeconds: 0 };
  await check();
  metrics = { ...metrics, oldestPendingJobAgeSeconds: 400 };
  await check();
  assert.deepEqual(alerts.slice(4), ["oldest-job"]);
});
