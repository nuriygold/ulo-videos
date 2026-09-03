import test from "node:test";
import assert from "node:assert/strict";
import { submitRenderJob } from "../src/web/job-service";

test("submitRenderJob snapshots the scene before publishing only the job id", async () => {
  const source = { template: "interruption_spokescharacter_v1", output: { width: 1920 } };
  const saved: any[] = [];
  const messages: any[] = [];
  const job = await submitRenderJob({ id: "rj_1", workspaceId: "w_1", projectId: "p_1", shotId: "s_1", template: "interruption_spokescharacter_v1", templateVersion: 1, specSnapshot: source }, { create: async (value) => { saved.push(value); }, get: async () => null }, { publish: async (value) => { messages.push(value); } });
  source.output.width = 720;
  assert.equal(job.status, "queued");
  assert.equal(saved[0].specSnapshot.output.width, 1920);
  assert.deepEqual(messages, [{ renderJobId: "rj_1" }]);
});
