const express = require("express");
const multer = require("multer");
const crypto = require("crypto");
const path = require("path");
const Photo = require("../models/Photo");
const Album = require("../models/Album");
const { requireAuth, requireWorker } = require("../middleware/auth");
const { uploadImage, createSignedReadUrl } = require("../services/storage.service");
const { publishPhotoUploaded } = require("../services/queue.service");

const router = express.Router();
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 10 * 1024 * 1024, files: 1 },
  fileFilter: (req, file, cb) => {
    const allowed = ["image/jpeg", "image/png", "image/webp"];
    if (!allowed.includes(file.mimetype)) return cb(new Error("Only JPEG, PNG and WEBP images are allowed"));
    cb(null, true);
  }
});

/**
 * @swagger
 * /api/photos/upload:
 *   post:
 *     summary: Upload an image to Google Cloud Storage and publish a Pub/Sub event
 *     security:
 *       - bearerAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         multipart/form-data:
 *           schema:
 *             type: object
 *             required: [image, albumId]
 *             properties:
 *               image: { type: string, format: binary }
 *               albumId: { type: string }
 *     responses:
 *       201:
 *         description: Image uploaded; processing queued when Pub/Sub is configured
 */
router.post("/upload", requireAuth, upload.single("image"), async (req, res, next) => {
  let createdPhoto;
  let uploadedObject;
  try {
    if (!req.file) return res.status(400).json({ success: false, message: "Image file is required (field: image)" });

    const album = await Album.findOne({ _id: req.body.albumId, ownerId: req.user.id });
    if (!album) return res.status(404).json({ success: false, message: "Album not found or not owned by current user" });

    const ext = path.extname(req.file.originalname).toLowerCase() || ".jpg";
    const objectName = `original/${req.user.id}/${album._id}/${crypto.randomUUID()}${ext}`;
    uploadedObject = objectName;

    await uploadImage(req.file.buffer, objectName, req.file.mimetype);

    createdPhoto = await Photo.create({
      albumId: album._id,
      ownerId: req.user.id,
      originalObject: objectName,
      originalName: req.file.originalname,
      mimeType: req.file.mimetype,
      size: req.file.size,
      status: "PENDING",
      progress: 0
    });

    let queue = { published: false, messageId: null, reason: "Pub/Sub not configured" };
    try {
      queue = await publishPhotoUploaded(createdPhoto);
      if (queue.published) {
        createdPhoto.queuePublished = true;
        createdPhoto.queueMessageId = queue.messageId;
        await createdPhoto.save();
      }
    } catch (queueError) {
      createdPhoto.errorMessage = `Queue publish failed: ${queueError.message}`;
      await createdPhoto.save();
      return res.status(503).json({
        success: false,
        message: "Image uploaded, but the processing event could not be queued. Ask an administrator to retry dispatch.",
        photoId: String(createdPhoto._id),
        queuePublished: false
      });
    }

    const originalUrl = await createSignedReadUrl(objectName);
    res.status(201).json({
      success: true,
      message: "Image uploaded",
      photo: {
        id: createdPhoto._id,
        albumId: createdPhoto.albumId,
        status: createdPhoto.status,
        progress: createdPhoto.progress,
        originalUrl
      },
      queue
    });
  } catch (err) {
    if (uploadedObject && !createdPhoto) {
      // Best-effort cleanup for a failed database insert.
      try {
        const { deleteObject } = require("../services/storage.service");
        await deleteObject(uploadedObject);
      } catch (_) {}
    }
    next(err);
  }
});

/**
 * @swagger
 * /api/photos:
 *   get:
 *     summary: List current user's photos
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: query
 *         name: albumId
 *         schema: { type: string }
 *     responses:
 *       200:
 *         description: Photo list with short-lived signed read URLs
 */
router.get("/", requireAuth, async (req, res, next) => {
  try {
    const filter = { ownerId: req.user.id };
    if (req.query.albumId) filter.albumId = req.query.albumId;

    const photos = await Photo.find(filter).sort({ createdAt: -1 }).limit(100).lean();
    const results = await Promise.all(photos.map(async photo => ({
      ...photo,
      originalUrl: await createSignedReadUrl(photo.originalObject),
      thumbnailUrl: await createSignedReadUrl(photo.thumbnailObject)
    })));

    res.json({ success: true, count: results.length, photos: results });
  } catch (err) {
    next(err);
  }
});

/**
 * @swagger
 * /api/photos/{id}/status:
 *   get:
 *     summary: Get image processing status
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema: { type: string }
 *     responses:
 *       200:
 *         description: Processing status
 *       404:
 *         description: Photo not found
 */
router.get("/:id/status", requireAuth, async (req, res, next) => {
  try {
    const photo = await Photo.findOne({ _id: req.params.id, ownerId: req.user.id }).lean();
    if (!photo) return res.status(404).json({ success: false, message: "Photo not found" });

    res.json({
      success: true,
      photoId: photo._id,
      status: photo.status,
      progress: photo.progress,
      errorMessage: photo.errorMessage,
      updatedAt: photo.updatedAt
    });
  } catch (err) {
    next(err);
  }
});

/**
 * @swagger
 * /api/photos/{id}/worker-status:
 *   patch:
 *     summary: Worker-only endpoint to update processing status
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema: { type: string }
 *       - in: header
 *         name: x-worker-secret
 *         required: true
 *         schema: { type: string }
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               status: { type: string, enum: [PENDING, PROCESSING, COMPLETED, FAILED] }
 *               progress: { type: integer, minimum: 0, maximum: 100 }
 *               thumbnailObject: { type: string }
 *               errorMessage: { type: string }
 *     responses:
 *       200:
 *         description: Status updated
 */
router.patch("/:id/worker-status", requireWorker, async (req, res, next) => {
  try {
    const allowed = ["PENDING", "PROCESSING", "COMPLETED", "FAILED"];
    const { status, progress, thumbnailObject, errorMessage } = req.body;

    if (!allowed.includes(status)) {
      return res.status(400).json({ success: false, message: "Invalid status" });
    }
    if (progress !== undefined && (!Number.isInteger(progress) || progress < 0 || progress > 100)) {
      return res.status(400).json({ success: false, message: "Progress must be an integer from 0 to 100" });
    }

    const update = { status, updatedAt: new Date() };
    if (progress !== undefined) update.progress = progress;
    if (thumbnailObject !== undefined) update.thumbnailObject = thumbnailObject;
    if (errorMessage !== undefined) update.errorMessage = errorMessage;
    if (status === "COMPLETED") {
      update.progress = 100;
      update.errorMessage = null;
    }

    const photo = await Photo.findByIdAndUpdate(req.params.id, update, { new: true, runValidators: true });
    if (!photo) return res.status(404).json({ success: false, message: "Photo not found" });

    res.json({ success: true, photoId: photo._id, status: photo.status, progress: photo.progress });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
