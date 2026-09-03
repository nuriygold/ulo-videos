import test from "node:test";
import assert from "node:assert/strict";
import { rendererHealthForQueue, setupStatus } from "../src/web/setup-status";

test("setupStatus reports every configured production dependency as ready", () => {
  assert.deepEqual(setupStatus({ SUPABASE_URL: "url", SUPABASE_SERVICE_ROLE_KEY: "key", BLOB_READ_WRITE_TOKEN: "blob", RENDER_QUEUE_URL: "queue", RENDER_WORKER_SECRET: "secret" }), {
    ready: true,
    services: { blob: true, supabase: true, queue: true, worker: true },
    renderer: {
      mode: "vercel_fallback",
      reachable: true,
      capabilities: { freezeResume: true, logo: true, captions: true, character: false, sourceAudio: false, speech: false, lipSync: false, characterFormats: [] },
    },
  });
});

test("setupStatus identifies only the missing dependency", () => {
  assert.deepEqual(setupStatus({ SUPABASE_URL: "url", SUPABASE_SERVICE_ROLE_KEY: "key", BLOB_READ_WRITE_TOKEN: "blob", RENDER_QUEUE_URL: "", RENDER_WORKER_SECRET: "secret" }), {
    ready: false,
    services: { blob: true, supabase: true, queue: false, worker: true },
    renderer: {
      mode: "vercel_fallback",
      reachable: false,
      capabilities: { freezeResume: true, logo: true, captions: true, character: false, sourceAudio: false, speech: false, lipSync: false, characterFormats: [] },
    },
  });
});

test("renderer health selects external capabilities only when its health response is ready", async () => {
  const health = await rendererHealthForQueue("https://renderer.example/healthz", async () => Response.json({ ok: true, mode: "external_worker" }));
  assert.deepEqual(health, { mode: "external_worker", reachable: true });
  assert.deepEqual(setupStatus({ SUPABASE_URL: "url", SUPABASE_SERVICE_ROLE_KEY: "key", BLOB_READ_WRITE_TOKEN: "blob", RENDER_QUEUE_URL: "queue", RENDER_WORKER_SECRET: "secret" }, health).renderer.capabilities, {
    freezeResume: true, logo: true, captions: true, character: true, sourceAudio: false, speech: false, lipSync: false, characterFormats: [".blend"],
  });
  assert.deepEqual(await rendererHealthForQueue("https://renderer.example/healthz", async () => Response.json({ ok: false, mode: "external_worker" }, { status: 503 })), { mode: "vercel_fallback", reachable: false });
});
