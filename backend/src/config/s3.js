const { S3Client } = require("@aws-sdk/client-s3");

function s3Settings(env = process.env) {
  const names = ["S3_ENDPOINT", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET"];
  for (const name of names) {
    if (!env[name]) throw new Error(`${name} is required for S3 storage`);
  }
  const endpoint = new URL(env.S3_ENDPOINT);
  if ((endpoint.protocol !== "https:" &&
       !(endpoint.protocol === "http:" && ["localhost", "127.0.0.1"].includes(endpoint.hostname))) ||
      endpoint.username || endpoint.password || endpoint.search || endpoint.hash) {
    throw new Error("S3_ENDPOINT must be an HTTPS URL or a localhost test URL");
  }
  return {
    bucket: env.S3_BUCKET,
    options: {
      endpoint: endpoint.href,
      region: env.S3_REGION,
      forcePathStyle: true,
      credentials: { accessKeyId: env.S3_ACCESS_KEY_ID, secretAccessKey: env.S3_SECRET_ACCESS_KEY },
      requestChecksumCalculation: "WHEN_REQUIRED",
      responseChecksumValidation: "WHEN_REQUIRED",
      maxAttempts: 2
    }
  };
}

function createS3Storage() {
  const { bucket, options } = s3Settings();
  return { bucket, client: new S3Client(options) };
}

module.exports = { createS3Storage, s3Settings };
