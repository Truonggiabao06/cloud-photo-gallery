const jwt = require("jsonwebtoken");
const jwksClient = require("jwks-rsa");

const tenantId = process.env.ENTRA_TENANT_ID;
const audience = process.env.ENTRA_AUDIENCE || process.env.ENTRA_API_CLIENT_ID;

const client = jwksClient({
  jwksUri: `https://login.microsoftonline.com/${tenantId}/discovery/v2.0/keys`,
  cache: true,
  cacheMaxEntries: 5,
  cacheMaxAge: 10 * 60 * 1000,
  rateLimit: true
});

function getSigningKey(header, callback) {
  if (!header.kid) return callback(new Error("Token header has no kid"));
  client.getSigningKey(header.kid, (err, key) => {
    if (err) return callback(err);
    callback(null, key.getPublicKey());
  });
}

function requireAuth(req, res, next) {
  if (!tenantId || !audience) {
    return res.status(500).json({ success: false, message: "Entra configuration is incomplete" });
  }

  const header = req.headers.authorization || "";
  const [scheme, token] = header.split(" ");

  if (scheme !== "Bearer" || !token) {
    return res.status(401).json({ success: false, message: "Missing Bearer access token" });
  }

  jwt.verify(token, getSigningKey, {
    algorithms: ["RS256"],
    audience,
    issuer: `https://login.microsoftonline.com/${tenantId}/v2.0`
  }, (err, claims) => {
    if (err) {
      return res.status(401).json({ success: false, message: "Invalid or expired Entra access token" });
    }

    if (claims.tid !== tenantId || !claims.sub) {
      return res.status(403).json({ success: false, message: "Token tenant or subject is not allowed" });
    }

    // Configure the delegated API scope in Entra and request it from the frontend.
    const scopes = String(claims.scp || "").split(" ");
    if (process.env.REQUIRED_API_SCOPE && !scopes.includes(process.env.REQUIRED_API_SCOPE)) {
      return res.status(403).json({ success: false, message: "Required API scope is missing" });
    }

    req.user = {
      id: claims.sub,
      name: claims.name || "",
      email: claims.preferred_username || claims.email || ""
    };
    next();
  });
}

function requireWorker(req, res, next) {
  const expected = process.env.WORKER_SHARED_SECRET;
  const received = req.get("x-worker-secret");

  if (!expected || !received || received !== expected) {
    return res.status(401).json({ success: false, message: "Worker authentication failed" });
  }
  next();
}

module.exports = { requireAuth, requireWorker };
