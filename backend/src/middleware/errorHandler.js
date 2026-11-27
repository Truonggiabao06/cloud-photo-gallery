function notFound(req, res) {
  res.status(404).json({ success: false, message: `Route not found: ${req.method} ${req.originalUrl}` });
}

function errorHandler(err, req, res, next) {
  console.error(err);

  if (err.code === "LIMIT_FILE_SIZE") {
    return res.status(413).json({ success: false, message: "Image exceeds the 10 MB limit" });
  }
  if (err.name === "MulterError") {
    return res.status(400).json({ success: false, message: err.message });
  }
  if (err.name === "ValidationError") {
    return res.status(400).json({ success: false, message: err.message });
  }
  if (err.name === "CastError") {
    return res.status(400).json({ success: false, message: "Invalid resource ID" });
  }

  res.status(err.status || 500).json({
    success: false,
    message: err.status ? err.message : "Internal server error"
  });
}

module.exports = { notFound, errorHandler };
