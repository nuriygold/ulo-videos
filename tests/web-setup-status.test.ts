import test from "node:test";
import assert from "node:assert/strict";
import { setupStatus } from "../src/web/setup-status";

test("setupStatus reports every configured production dependency as ready", () => {
  assert.deepEqual(setupStatus({ SUPABASE_URL: "url", SUPABASE_SERVICE_ROLE_KEY: "key", BLOB_READ_WRITE_TOKEN: "blob", RENDER_QUEUE_URL: "queue", RENDER_WORKER_SECRET: "secret" }), { ready: true, services: { blob: true, supabase: true, queue: true, worker: true } });
});

test("setupStatus identifies only the missing dependency", () => {
  assert.deepEqual(setupStatus({ SUPABASE_URL: "url", SUPABASE_SERVICE_ROLE_KEY: "key", BLOB_READ_WRITE_TOKEN: "blob", RENDER_QUEUE_URL: "", RENDER_WORKER_SECRET: "secret" }), { ready: false, services: { blob: true, supabase: true, queue: false, worker: true } });
});
