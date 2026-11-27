const express = require("express");
const { requireAuth } = require("../middleware/auth");

const router = express.Router();

/**
 * @swagger
 * /api/auth/me:
 *   get:
 *     summary: Validate Entra access token and return current user
 *     security:
 *       - bearerAuth: []
 *     responses:
 *       200:
 *         description: Authenticated user
 *       401:
 *         description: Missing, invalid or expired token
 */
router.get("/me", requireAuth, (req, res) => {
  res.json({ success: true, user: req.user });
});

module.exports = router;
