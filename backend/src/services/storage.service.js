const { PutObjectCommand, DeleteObjectCommand, GetObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");
const { getBucket } = require("../config/storage");
const { createS3Storage } = require("../config/s3");

let s3;
function s3Object(key) {
  s3 ||= createS3Storage();
  return { Bucket: s3.bucket, Key: key };
}

async function uploadImage(buffer, objectName, contentType) {
  if (process.env.STORAGE_BACKEND === "s3") {
    const target = s3Object(objectName);
    await s3.client.send(new PutObjectCommand({
      ...target, Body: buffer, ContentType: contentType, CacheControl: "private, max-age=0, no-transform"
    }), { abortSignal: AbortSignal.timeout(15000) });
    return objectName;
  }
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
  if (process.env.STORAGE_BACKEND === "s3") {
    const object = s3Object(objectName);
    return getSignedUrl(s3.client, new GetObjectCommand(object), { expiresIn: 900 });
  }
  const [url] = await getBucket().file(objectName).getSignedUrl({
    version: "v4",
    action: "read",
    expires: Date.now() + 15 * 60 * 1000
  });
  return url;
}

async function deleteObject(objectName) {
  if (!objectName) return;
  if (process.env.STORAGE_BACKEND === "s3") {
    const object = s3Object(objectName);
    await s3.client.send(new DeleteObjectCommand(object), { abortSignal: AbortSignal.timeout(10000) });
    return;
  }
  await getBucket().file(objectName).delete({ ignoreNotFound: true });
}

module.exports = { uploadImage, createSignedReadUrl, deleteObject };
