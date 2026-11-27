const pubsub = require("../config/pubsub");

async function publishPhotoUploaded(photo) {
  const topicName = process.env.PUBSUB_TOPIC;
  if (!topicName) {
    // Local development can run without Pub/Sub. Set topic to enable worker dispatch.
    return { published: false, messageId: null, reason: "PUBSUB_TOPIC is not configured" };
  }

  const payload = {
    eventType: "PHOTO_UPLOADED",
    eventVersion: 1,
    photoId: String(photo._id),
    albumId: String(photo.albumId),
    userId: photo.ownerId,
    bucket: process.env.GCS_BUCKET_NAME,
    originalObject: photo.originalObject,
    mimeType: photo.mimeType,
    createdAt: photo.createdAt.toISOString()
  };

  const messageId = await pubsub.topic(topicName).publishMessage({
    data: Buffer.from(JSON.stringify(payload)),
    attributes: {
      eventType: "PHOTO_UPLOADED",
      photoId: String(photo._id)
    }
  });

  return { published: true, messageId };
}

module.exports = { publishPhotoUploaded };
