const { getBucket } = require("../config/storage");

async function uploadImage(buffer, objectName, contentType) {
  const bucket = getBucket();
  const file = bucket.file(objectName);

  await file.save(buffer, {
    resumable: false,
    validation: "crc32c",
    metadata: {
      contentType,
      cacheControl: "private, max-age=0, no-transform"
    },
    preconditionOpts: { ifGenerationMatch: 0 }
  });

  return objectName;
}

async function createSignedReadUrl(objectName) {
  if (!objectName) return null;
  const [url] = await getBucket().file(objectName).getSignedUrl({
    version: "v4",
    action: "read",
    expires: Date.now() + 15 * 60 * 1000
  });
  return url;
}

async function deleteObject(objectName) {
  if (!objectName) return;
  await getBucket().file(objectName).delete({ ignoreNotFound: true });
}

module.exports = { uploadImage, createSignedReadUrl, deleteObject };
