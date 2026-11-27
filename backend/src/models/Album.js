const mongoose = require("mongoose");

const albumSchema = new mongoose.Schema({
  name: { type: String, required: true, trim: true, maxlength: 120 },
  description: { type: String, default: "", maxlength: 1000 },
  ownerId: { type: String, required: true, index: true },
  createdAt: { type: Date, default: Date.now }
});

albumSchema.index({ ownerId: 1, createdAt: -1 });

module.exports = mongoose.model("Album", albumSchema);
