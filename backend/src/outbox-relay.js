require("dotenv").config();

const pubsub = require("./config/pubsub");
const { connectDatabase, closeDatabase } = require("./config/database");
const { dispatchNext } = require("./services/outbox-relay.service");

async function run() {
  if (!process.env.PUBSUB_TOPIC) throw new Error("PUBSUB_TOPIC is missing");
  await connectDatabase();
  const deadline = Date.now() + 75_000;
  const results = {};
  for (let index = 0; index < 500 && Date.now() < deadline; index += 1) {
    const outcome = await dispatchNext();
    if (!outcome) break;
    results[outcome] = (results[outcome] || 0) + 1;
  }
  console.log(JSON.stringify({ event: "outbox_relay_finished", results }));
}

run().catch(error => {
  console.error(JSON.stringify({ event: "outbox_relay_failed", errorType: error.name }));
  process.exitCode = 1;
}).finally(async () => {
  await Promise.all([closeDatabase(), pubsub.close()]);
});
