import test from "node:test";
import assert from "node:assert/strict";
import { authorizeQueueRequest, queueMessageFromRequest, queueRejectionMessage } from "../src/web/render-queue";

test("queue endpoint accepts only the worker secret and a render job id", async () => {
  const request = new Request("https://ulo-videos.vercel.app/api/render-jobs/queue", { method: "POST", headers: { authorization: "Bearer secret" }, body: JSON.stringify({ renderJobId: "rj_123" }) });
  assert.equal(authorizeQueueRequest(request, "secret"), true);
  assert.deepEqual(await queueMessageFromRequest(request), { renderJobId: "rj_123" });
});

test("queue endpoint rejects malformed messages and wrong secrets", async () => {
  const request = new Request("https://ulo-videos.vercel.app/api/render-jobs/queue", { method: "POST", headers: { authorization: "Bearer wrong" }, body: JSON.stringify({}) });
  assert.equal(authorizeQueueRequest(request, "secret"), false);
  await assert.rejects(queueMessageFromRequest(request), /renderJobId/);
});

test("queue endpoint rejects render job ids with path separators", async () => {
  await assert.rejects(queueMessageFromRequest(new Request("https://ulo-videos.vercel.app/api/render-jobs/queue", { method: "POST", body: JSON.stringify({ renderJobId: "rj_../secret" }) })), /renderJobId/);
  await assert.rejects(queueMessageFromRequest(new Request("https://ulo-videos.vercel.app/api/render-jobs/queue", { method: "POST", body: JSON.stringify({ renderJobId: "rj_..\\secret" }) })), /renderJobId/);
  assert.deepEqual(await queueMessageFromRequest(new Request("https://ulo-videos.vercel.app/api/render-jobs/queue", { method: "POST", body: JSON.stringify({ renderJobId: "rj_abc-123_DEF" }) })), { renderJobId: "rj_abc-123_DEF" });
});

test("queue rejection diagnostics preserve response body but redact bearer tokens", () => {
  assert.equal(queueRejectionMessage(502, "dispatcher unavailable for rj_123"), "render queue rejected the job (502): dispatcher unavailable for rj_123");
  assert.equal(queueRejectionMessage(401, "Authorization: Bearer super-secret-token"), "render queue rejected the job (401): Authorization: Bearer [redacted]");
});
