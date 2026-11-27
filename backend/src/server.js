require("dotenv").config();

const express = require("express");
const cors = require("cors");
const helmet = require("helmet");
const morgan = require("morgan");
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

app.use(helmet());
app.use(cors({
  origin: (origin, callback) => {
    if (!origin || origins.includes(origin)) return callback(null, true);
    callback(new Error("Origin not allowed by CORS"));
  }
}));
app.use(express.json({ limit: "1mb" }));
app.use(morgan("dev"));
app.use(rateLimit({ windowMs: 15 * 60 * 1000, limit: 300 }));

app.get("/", (req, res) => {
  res.json({ name: "Cloud Photo Gallery API", status: "running", docs: "/api-docs" });
});
app.get(["/health", "/api/health"], (req, res) => res.json({ success: true, status: "OK" }));
app.use("/api-docs", swaggerUi.serve, swaggerUi.setup(swaggerSpec));

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
    console.error("Startup failed:", err.message);
    process.exit(1);
  });
