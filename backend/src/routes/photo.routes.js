const express = require("express");
const multer = require("multer");
const crypto = require("crypto");
const path = require("path");
const gallery = require("../services/gallery.service");
const { requireAuth, requireWorker } = require("../middleware/auth");
const { uploadImage, createSignedReadUrl, deleteObject } = require("../services/storage.service");
const { createPhotoJob, updatePhotoJob } = require("../services/photo-jobs.service");

const { wakeWorker } = require("../services/worker-wake.service");

const router = express.Router();
const filenameDecoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 10 * 1024 * 1024, files: 1 },
  fileFilter: (req, file, cb) => {
    const allowed = ["image/jpeg", "image/png", "image/webp"];
    if (!allowed.includes(file.mimetype)) return cb(Object.assign(new Error("Unsupported image type"), { code: "UNSUPPORTED_IMAGE_TYPE" }));
    cb(null, true);
  }
});

function decodeUploadFilename(filename) {
  // Busboy may expose the UTF-8 bytes of a plain multipart filename as Latin-1.
  if (/[^\u0000-\u00ff]/u.test(filename)) return filename;
  try {
    return filenameDecoder.decode(Buffer.from(filename, "latin1"));
  } catch {
    return filename;
  }
}

/**
 * @swagger
 * /api/photos/upload:
 *   post:
 *     summary: Upload an image and enqueue an Outbox event
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
 *         description: Image uploaded; processing committed to the durable outbox
 */
router.post("/upload", requireAuth, upload.single("image"), async (req, res, next) => {
  let createdPhoto;
  let uploadedObject;

  try {
    if (!req.file?.size) return res.status(400).json({ success: false, message: "Image file is required (field: image)" });

    const album = await gallery.findOwnedAlbum(req.user.id, req.body.albumId);
    if (!album) return res.status(404).json({ success: false, message: "Album not found or not owned by current user" });

    const originalName = decodeUploadFilename(req.file.originalname);
    if (originalName.length > 255) {
      return res.status(400).json({ success: false, message: "Filename must be at most 255 characters" });
    }
    const ext = path.extname(originalName).toLowerCase() || ".jpg";
    const objectName = `original/${req.user.id}/${album.id}/${crypto.randomUUID()}${ext}`;
    await uploadImage(req.file.buffer, objectName, req.file.mimetype);
    uploadedObject = objectName;
    const originalUrl = await createSignedReadUrl(objectName);
    const id = crypto.randomUUID();
    createdPhoto = await createPhotoJob({
      _id: id,
      albumId: album.id,
      ownerId: req.user.id,
      originalObject: objectName,
      originalName,
      mimeType: req.file.mimetype,
      size: req.file.size,
      requestId: req.requestId,
      checksumSha256: crypto.createHash("sha256").update(req.file.buffer).digest("hex")
    });

    req.photoId = createdPhoto._id;
    req.jobId = createdPhoto.jobId;
    wakeWorker();
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
      queue: { queued: true, published: false, messageId: null, eventId: id }
    });
  } catch (err) {
    if (uploadedObject && !createdPhoto) {
      // Best-effort cleanup for a failed database insert.
      try {
        if (!err.commitUnknown) {
          await deleteObject(uploadedObject);
        }
      } catch (_) {}
    }
    next(err);
  }
});

/**
 * @swagger
 * /api/photos:
 *   get:
 *     summary: List photos in visible albums
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
    const photos = await gallery.listPhotos(req.user.id, req.query.albumId);
    const results = await Promise.all(photos.map(async photo => {
      const [originalUrl, small, large] = await Promise.all([
        createSignedReadUrl(photo.originalObject),
        createSignedReadUrl(photo.thumbnailSmallObject),
        createSignedReadUrl(photo.thumbnailLargeObject || photo.thumbnailObject)
      ]);
      return { ...photo, originalUrl, thumbnailUrl: large, thumbnailUrls: { small, large } };
    }));

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
    const photo = await gallery.findPhoto(req.user.id, req.params.id);
    if (!photo) return res.status(404).json({ success: false, message: "Photo not found" });

    req.photoId = photo._id;
    req.jobId = photo.jobId;
    res.json({
      success: true,
      jobId: photo.jobId,
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
 *               thumbnailSmallObject: { type: string }
 *               thumbnailLargeObject: { type: string }
 *               errorMessage: { type: string }
 *     responses:
 *       200:
 *         description: Status updated
 */
router.patch("/:id/worker-status", requireWorker, async (req, res, next) => {
  req.workerAuthenticated = true;
  if (gallery.isUuid(req.params.id)) req.photoId = req.params.id;
  try {
    const allowed = ["PENDING", "PROCESSING", "COMPLETED", "FAILED"];
    const { status, progress, thumbnailObject, thumbnailSmallObject, thumbnailLargeObject, errorMessage, thumbnailBytes } = req.body;
    const leaseId = req.get("x-outbox-lease");
    if (process.env.STORAGE_BACKEND === "s3" && !gallery.isUuid(leaseId)) {
      return res.status(409).json({ success: false, message: "Outbox lease required" });
    }

    if (!allowed.includes(status)) {
      return res.status(400).json({ success: false, message: "Invalid status" });
    }
    if (progress !== undefined && (!Number.isInteger(progress) || progress < 0 || progress > 100)) {
      return res.status(400).json({ success: false, message: "Progress must be an integer from 0 to 100" });
    }

    const update = { status };
    if (progress !== undefined) update.progress = progress;
    if (!gallery.isUuid(req.params.id)) {
      return res.status(400).json({ success: false, message: "Invalid photo ID" });
    }
    if (status === "FAILED") {
      update.errorMessage = typeof errorMessage === "string" && errorMessage.trim()
        ? errorMessage.trim().slice(0, 500) : "Image processing failed";
    }
    if (status === "COMPLETED") {
      const id = req.params.id.toLowerCase();
      const expectedSmall = `thumbnails/${id}/small.webp`;
      const expectedLarge = `thumbnails/${id}/large.webp`;
      if (process.env.STORAGE_BACKEND === "s3" &&
          (!Number.isSafeInteger(thumbnailBytes) || thumbnailBytes < 1 || thumbnailBytes > 10485760)) {
        return res.status(400).json({ success: false, message: "Valid thumbnailBytes is required" });
      }
      if (Number.isSafeInteger(thumbnailBytes) && thumbnailBytes > 0 && thumbnailBytes <= 10485760) {
        update.thumbnailBytes = thumbnailBytes;
      }
      if (thumbnailSmallObject !== expectedSmall || (thumbnailLargeObject || thumbnailObject) !== expectedLarge) {
        return res.status(400).json({ success: false, message: "Both deterministic thumbnail keys are required" });
      }
    }

    const { photo, alreadyTerminal, terminalCommit, leaseLost } = await updatePhotoJob(req.params.id, update,
      process.env.STORAGE_BACKEND === "s3" ? leaseId : undefined);
    if (leaseLost) return res.status(409).json({ success: false, message: "Outbox lease expired" });
    if (!photo) return res.status(404).json({ success: false, message: "Photo not found" });

    req.jobId = photo.jobId;
    res.json({
      success: true, photoId: photo._id, jobId: photo.jobId, status: photo.status,
      progress: photo.progress, alreadyTerminal, terminalCommit
    });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
