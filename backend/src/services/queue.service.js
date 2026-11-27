const pubsub = require("../config/pubsub");

function photoUploadedPayload(photo) {
  const bucket = process.env.GCS_BUCKET_NAME;
  if (!bucket) throw new Error("GCS_BUCKET_NAME is missing");
  return {
    eventType: "PHOTO_UPLOADED",
    eventVersion: 1,
    photoId: String(photo._id),
    jobId: photo.jobId,
    albumId: String(photo.albumId),
    userId: photo.ownerId,
    bucket,
    originalObject: photo.originalObject,
    mimeType: photo.mimeType,
    createdAt: photo.createdAt.toISOString()
  };
}

async function publishPhotoUploaded(payload) {
  const topicName = process.env.PUBSUB_TOPIC;
  if (!topicName) throw new Error("PUBSUB_TOPIC is missing");
  return pubsub.topic(topicName).publishMessage({
    data: Buffer.from(JSON.stringify(payload)),
    attributes: {
      eventType: payload.eventType,
      photoId: payload.photoId,
      eventId: payload.photoId
    }
  });
}

module.exports = { photoUploadedPayload, publishPhotoUploaded };
