const mongoose = require("mongoose");

const photoSchema = new mongoose.Schema({
  albumId: { type: mongoose.Schema.Types.ObjectId, ref: "Album", required: true, index: true },
  ownerId: { type: String, required: true, index: true },
  originalObject: { type: String, required: true },
  thumbnailObject: { type: String, default: null },
  originalUrl: { type: String, default: null },
  thumbnailUrl: { type: String, default: null },
  originalName: { type: String, required: true },
  mimeType: { type: String, required: true },
  size: { type: Number, required: true },
  status: {
    type: String,
    enum: ["PENDING", "PROCESSING", "COMPLETED", "FAILED"],
    default: "PENDING",
    index: true
  },
  progress: { type: Number, default: 0, min: 0, max: 100 },
  errorMessage: { type: String, default: null },
  queueMessageId: { type: String, default: null },
  queuePublished: { type: Boolean, default: false },
  createdAt: { type: Date, default: Date.now },
  updatedAt: { type: Date, default: Date.now }
});

photoSchema.index({ ownerId: 1, createdAt: -1 });
photoSchema.index({ albumId: 1, createdAt: -1 });

module.exports = mongoose.model("Photo", photoSchema);
