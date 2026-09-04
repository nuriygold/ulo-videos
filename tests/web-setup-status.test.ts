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
  const health = await rendererHealthForQueue("https://dispatcher.example/render-jobs", async () => Response.json({ ok: true, mode: "external_worker", capabilities: { characterFormats: [".blend", ".gltf", ".glb", ".fbx"] } }), { healthUrl: "https://renderer.example/healthz" });
  assert.deepEqual(health, { mode: "external_worker", reachable: true, characterFormats: [".blend", ".gltf", ".glb", ".fbx"] });
  assert.deepEqual(setupStatus({ SUPABASE_URL: "url", SUPABASE_SERVICE_ROLE_KEY: "key", BLOB_READ_WRITE_TOKEN: "blob", RENDER_QUEUE_URL: "queue", RENDER_WORKER_SECRET: "secret" }, health).renderer.capabilities, {
    freezeResume: true, logo: true, captions: true, character: true, sourceAudio: false, speech: false, lipSync: false, characterFormats: [".blend", ".gltf", ".glb", ".fbx"],
  });
  assert.deepEqual(await rendererHealthForQueue("https://dispatcher.example/render-jobs", async () => Response.json({ ok: false, mode: "external_worker" }, { status: 503 }), { healthUrl: "https://renderer.example/healthz" }), { mode: "vercel_fallback", reachable: false });
});

test("renderer status does not advertise imported formats that the worker did not report", async () => {
  const health = await rendererHealthForQueue("https://dispatcher.example/render-jobs", async () => Response.json({ ok: true, mode: "external_worker", capabilities: { characterFormats: [".blend"] } }), { healthUrl: "https://renderer.example/healthz" });
  assert.deepEqual(setupStatus({ RENDER_QUEUE_URL: "queue" }, health).renderer.capabilities.characterFormats, [".blend"]);
});

test("renderer status advertises only worker-reported character formats", async () => {
  const health = await rendererHealthForQueue("https://dispatcher.example/render-jobs", async () => Response.json({ ok: true, mode: "external_worker", capabilities: { characterFormats: [".gltf"] } }), { healthUrl: "https://renderer.example/healthz" });
  assert.deepEqual(setupStatus({ RENDER_QUEUE_URL: "queue" }, health).renderer.capabilities.characterFormats, [".gltf"]);
});

test("renderer health does not GET a POST-only queue URL", async () => {
  let called = false;
  const health = await rendererHealthForQueue("https://dispatcher.example/render-jobs", async () => {
    called = true;
    return Response.json({ ok: false }, { status: 405 });
  });
  assert.equal(called, false);
  assert.deepEqual(health, { mode: "vercel_fallback", reachable: true });
});

test("renderer health uses a separate worker health URL when configured", async () => {
  const requested: string[] = [];
  const health = await rendererHealthForQueue("https://dispatcher.example/render-jobs", async (url) => {
    requested.push(String(url));
    return Response.json({ ok: true, mode: "external_worker", capabilities: { characterFormats: [".blend"] } });
  }, { healthUrl: "https://worker.example/healthz" });
  assert.deepEqual(requested, ["https://worker.example/healthz"]);
  assert.deepEqual(health, { mode: "external_worker", reachable: true, characterFormats: [".blend"] });
});

test("renderer health still probes the known Vercel fallback health endpoint", async () => {
  let called = false;
  const health = await rendererHealthForQueue("https://ulo-videos.vercel.app/api/render-queue", async () => {
    called = true;
    return Response.json({ ok: true, mode: "vercel_fallback" });
  });
  assert.equal(called, true);
  assert.deepEqual(health, { mode: "vercel_fallback", reachable: true });
});
