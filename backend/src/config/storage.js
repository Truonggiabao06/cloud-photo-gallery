const { Storage } = require("@google-cloud/storage");

const storage = new Storage({
  projectId: process.env.GCP_PROJECT_ID || undefined
});

function getBucket() {
  if (!process.env.GCS_BUCKET_NAME) {
    throw new Error("GCS_BUCKET_NAME is missing");
  }
  return storage.bucket(process.env.GCS_BUCKET_NAME);
}

module.exports = { storage, getBucket };
