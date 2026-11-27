const { PubSub } = require("@google-cloud/pubsub");

const pubsub = new PubSub({
  projectId: process.env.GCP_PROJECT_ID || undefined
});

module.exports = pubsub;
