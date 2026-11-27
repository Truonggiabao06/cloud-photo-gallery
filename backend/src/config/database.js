const { Pool } = require("pg");

let pool;
let connector;

async function connectDatabase() {
  const {
    DATABASE_URL: connectionString, CLOUD_SQL_INSTANCE: instanceConnectionName,
    DB_NAME: database, DB_USER: user, DB_PASS: password
  } = process.env;
  if (!connectionString && !(instanceConnectionName && database && user && password)) {
    throw new Error("Set DATABASE_URL or Cloud SQL instance and database credentials");
  }

  let options = { connectionString };
  if (instanceConnectionName && !connectionString) {
    const { Connector } = require("@google-cloud/cloud-sql-connector");
    connector = new Connector();
    const transport = await connector.getOptions({ instanceConnectionName, ipType: "PRIVATE" });
    options = { ...transport, database, user, password };
  }
  pool = new Pool({ ...options, max: 5, connectionTimeoutMillis: 5000 });
  pool.on("error", error => console.error("Idle PostgreSQL connection failed", error.code || error.name));

  // Detect unapplied migrations before a new revision receives traffic.
  await pool.query("SELECT i.progress, e.lease_id FROM images i CROSS JOIN outbox_events e LIMIT 0");
  console.log("PostgreSQL connected");
}

const query = (...args) => pool.query(...args);

async function closeDatabase() {
  try {
    await pool?.end();
  } finally {
    connector?.close();
  }
}

async function transaction(operation) {
  const client = await pool.connect();
  let committing = false;
  let unusable;
  try {
    await client.query("BEGIN");
    const result = await operation(client);
    committing = true;
    await client.query("COMMIT");
    return result;
  } catch (error) {
    if (committing) error.commitUnknown = true;
    try {
      await client.query("ROLLBACK");
    } catch (rollbackError) {
      unusable = rollbackError;
    }
    throw error;
  } finally {
    client.release(unusable);
  }
}

module.exports = { connectDatabase, closeDatabase, query, transaction };
