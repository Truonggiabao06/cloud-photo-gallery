function notFound(req, res) {
  res.status(404).json({ success: false, message: "Route not found" });
}

function errorHandler(err, req, res, next) {
  if (err.code === "UNSUPPORTED_IMAGE_TYPE") {
    return res.status(400).json({ success: false, message: "Chỉ hỗ trợ ảnh JPEG, PNG và WebP." });
  }

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

  const status = Number.isInteger(err.status) && err.status >= 400 && err.status < 500 ? err.status : 500;
  if (status === 500) console.error(JSON.stringify({ event: "request_error", requestId: req.requestId }));
  res.status(status).json({
    success: false,
    message: status < 500 ? err.message : "Internal server error"
  });
}

module.exports = { notFound, errorHandler };
