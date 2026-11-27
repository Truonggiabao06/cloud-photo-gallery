const express = require("express");
const gallery = require("../services/gallery.service");
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
    if (typeof name !== "string" || !name.trim() || name.trim().length > 150) {
      return res.status(400).json({ success: false, message: "Album name must be 1 to 150 characters" });
    }

    if (typeof description !== "string") {
      return res.status(400).json({ success: false, message: "Description must be a string" });
    }
    const album = await gallery.createAlbum(name.trim(), description, req.user.id);

    res.status(201).json({ success: true, album });
  } catch (err) {
    next(err);
  }
});

/**
 * @swagger
 * /api/albums:
 *   get:
 *     summary: List albums visible to the current user
 *     security:
 *       - bearerAuth: []
 *     responses:
 *       200:
 *         description: Album list
 */
router.get("/", async (req, res, next) => {
  try {
    const albums = await gallery.listAlbums(req.user.id);
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
    const album = await gallery.findAlbum(req.user.id, req.params.id);
    if (!album) return res.status(404).json({ success: false, message: "Album not found" });
    res.json({ success: true, album });
  } catch (err) {
    next(err);
  }
});

router.post("/:id/members", async (req, res, next) => {
  try {
    const { memberId } = req.body;
    if (typeof memberId !== "string" || !memberId.trim() || memberId.length > 255 ||
        memberId !== memberId.trim() || memberId === req.user.id) {
      return res.status(400).json({ success: false, message: "A different user's Entra subject is required" });
    }
    const member = await gallery.inviteViewer(req.user.id, req.params.id, memberId);
    if (!member) return res.status(404).json({ success: false, message: "Album not found" });
    res.json({ success: true, member });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
