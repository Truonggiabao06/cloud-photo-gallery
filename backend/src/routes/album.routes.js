const express = require("express");
const Album = require("../models/Album");
const Photo = require("../models/Photo");
const { requireAuth } = require("../middleware/auth");

const router = express.Router();
router.use(requireAuth);

/**
 * @swagger
 * /api/albums:
 *   post:
 *     summary: Create an album
 *     security:
 *       - bearerAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required: [name]
 *             properties:
 *               name: { type: string, example: Holiday 2026 }
 *               description: { type: string, example: Family trip photos }
 *     responses:
 *       201:
 *         description: Album created
 */
router.post("/", async (req, res, next) => {
  try {
    const { name, description = "" } = req.body;
    if (!name || !String(name).trim()) {
      return res.status(400).json({ success: false, message: "Album name is required" });
    }

    const album = await Album.create({
      name: String(name).trim(),
      description,
      ownerId: req.user.id
    });

    res.status(201).json({ success: true, album });
  } catch (err) {
    next(err);
  }
});

/**
 * @swagger
 * /api/albums:
 *   get:
 *     summary: List albums owned by current user
 *     security:
 *       - bearerAuth: []
 *     responses:
 *       200:
 *         description: Album list
 */
router.get("/", async (req, res, next) => {
  try {
    const albums = await Album.find({ ownerId: req.user.id }).sort({ createdAt: -1 }).lean();
    res.json({ success: true, count: albums.length, albums });
  } catch (err) {
    next(err);
  }
});

/**
 * @swagger
 * /api/albums/{id}:
 *   get:
 *     summary: Get album details and photo count
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema: { type: string }
 *     responses:
 *       200:
 *         description: Album details
 *       404:
 *         description: Album not found
 */
router.get("/:id", async (req, res, next) => {
  try {
    const album = await Album.findOne({ _id: req.params.id, ownerId: req.user.id }).lean();
    if (!album) return res.status(404).json({ success: false, message: "Album not found" });
    const photoCount = await Photo.countDocuments({ albumId: album._id, ownerId: req.user.id });
    res.json({ success: true, album: { ...album, photoCount } });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
