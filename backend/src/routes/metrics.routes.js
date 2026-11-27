const express = require("express");
const { createHash, timingSafeEqual } = require("node:crypto");
const { readMetrics } = require("../services/metrics.service");

const router = express.Router();
const digest = value => createHash("sha256").update(value).digest();

router.get("/", async (req, res, next) => {
  const token = process.env.OPS_METRICS_TOKEN;
  if (!token || token.length < 32) return res.sendStatus(404);
  const authorization = req.get("authorization") || "";
  if (!timingSafeEqual(digest(authorization), digest(`Bearer ${token}`))) {
    return res.sendStatus(401);
  }
  res.set("cache-control", "no-store");
  try {
    res.json(await readMetrics());
  } catch (error) {
    next(error);
  }
});

module.exports = router;
