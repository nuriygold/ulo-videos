import test from "node:test";
import assert from "node:assert/strict";
import { authorizeQueueRequest, queueMessageFromRequest } from "../src/web/render-queue";

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
