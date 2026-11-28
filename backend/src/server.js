require("dotenv").config();

const express = require("express");
const cors = require("cors");
const helmet = require("helmet");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const rateLimit = require("express-rate-limit");
const swaggerUi = require("swagger-ui-express");

const { connectDatabase } = require("./config/database");
const { workerOrigin } = require("./services/worker-wake.service");
const { s3Settings } = require("./config/s3");
const metricsRoutes = require("./routes/metrics.routes");
const { readMetrics } = require("./services/metrics.service");
const { loadAlertConfig, createAlertCheck } = require("./services/ops-alerts.service");
const swaggerSpec = require("./docs/swagger");
const authRoutes = require("./routes/auth.routes");
const albumRoutes = require("./routes/album.routes");
const photoRoutes = require("./routes/photo.routes");
const { notFound, errorHandler } = require("./middleware/errorHandler");

const app = express();
const origins = (process.env.CORS_ORIGINS || "http://localhost:5173").split(",").map(s => s.trim());

app.use((req, res, next) => {
  req.requestId = randomUUID();
  const parent = req.get("x-photo-upload-request-id");
  if (/^[a-f0-9-]{36}$/.test(parent || "")) req.parentRequestId = parent;
  res.set("X-Request-Id", req.requestId);
  const start = Date.now();
  res.on("finish", () => {
    const route = req.route?.path;
    console.log(JSON.stringify({
      event: "http_request", requestId: req.requestId,
      ...(req.workerAuthenticated && { parentRequestId: req.parentRequestId }),
      ...(req.photoId && { photoId: req.photoId }),
      ...(req.jobId && { jobId: req.jobId }),
      method: req.method, route: typeof route === "string" ? route : undefined,
      status: res.statusCode, elapsedMs: Date.now() - start
    }));
  });
  next();
});
app.use(helmet());
app.use(cors({
  origin: (origin, callback) => {
    if (!origin || origins.includes(origin)) return callback(null, true);
    callback(new Error("Origin not allowed by CORS"));
  }
}));
app.use(express.json({ limit: "1mb" }));
const proxyHops = process.env.HTTP_TRUST_PROXY_HOPS;
if (proxyHops) {
  if (!/^[1-5]$/.test(proxyHops)) throw new Error("HTTP_TRUST_PROXY_HOPS must be 1–5");
  app.set("trust proxy", Number(proxyHops));
}
const rateLimitMax = process.env.HTTP_RATE_LIMIT_PER_15_MIN || "300";
if (!/^[1-9][0-9]{0,4}$/.test(rateLimitMax)) throw new Error("Invalid HTTP_RATE_LIMIT_PER_15_MIN");
const publicLimit = rateLimit({ windowMs: 15 * 60 * 1000, limit: Number(rateLimitMax) });

app.get("/", (req, res) => {
  res.json({ name: "Cloud Photo Gallery API", status: "running", docs: "/api-docs" });
});
app.get(["/health", "/api/health"], (req, res) => res.json({ success: true, status: "OK" }));
app.use("/api-docs", swaggerUi.serve, swaggerUi.setup(swaggerSpec));
app.use("/ops", express.static(path.join(__dirname, "ops"), {
  setHeaders: response => response.set("Cache-Control", "no-store")
}));

app.use("/api", (req, res, next) => {
  // Worker callbacks authenticate inside the router and have no shared IP quota.
  if (req.method === "PATCH" && /^\/photos\/[a-f0-9-]{36}\/worker-status\/?$/i.test(req.path)) return next();
  return publicLimit(req, res, next);
});
app.use("/api/auth", authRoutes);
app.use("/api/albums", albumRoutes);
app.use("/api/photos", photoRoutes);
app.use("/api/metrics", metricsRoutes);

app.use(notFound);
app.use(errorHandler);

const port = process.env.PORT || 3000;

async function connect() {
  if (process.env.STORAGE_BACKEND === "s3") {
    s3Settings();
    workerOrigin();
  }
  const alertConfig = loadAlertConfig();
  await connectDatabase();
  if (alertConfig) {
    const check = createAlertCheck(alertConfig, { readMetrics });
    setInterval(check, 60000).unref();
  }
}

connect()
  .then(() => {
    app.listen(port, () => console.log(`Cloud Photo Gallery API: http://localhost:${port}`));
  })
  .catch(err => {
    console.error(JSON.stringify({ event: "startup_failed", errorType: err.constructor.name }));
    process.exit(1);
  });
