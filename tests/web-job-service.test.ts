import test from "node:test";
import assert from "node:assert/strict";
import { submitRenderJob, validateRendererCapabilitiesForScene } from "../src/web/job-service";

test("submitRenderJob snapshots the scene before publishing only the job id", async () => {
  const source = { template: "interruption_spokescharacter_v1", output: { width: 1920 }, elements: [] };
  const saved: any[] = [];
  const messages: any[] = [];
  const job = await submitRenderJob({ id: "rj_1", workspaceId: "w_1", projectId: "p_1", shotId: "s_1", template: "interruption_spokescharacter_v1", templateVersion: 1, specSnapshot: source }, { create: async (value) => { saved.push(value); }, get: async () => null, update: async () => {} }, { publish: async (value) => { messages.push(value); } });
  source.output.width = 720;
  assert.equal(job.status, "queued");
  assert.equal(saved[0].specSnapshot.output.width, 1920);
  assert.deepEqual(messages, [{ renderJobId: "rj_1" }]);
});

test("submitRenderJob marks a queued job failed when publishing is rejected", async () => {
  const updates: any[] = [];
  await assert.rejects(
    submitRenderJob({ id: "rj_2", workspaceId: "w_1", projectId: "p_1", shotId: "s_1", template: "interruption_spokescharacter_v1", templateVersion: 1, specSnapshot: { elements: [] } }, { create: async () => {}, get: async () => null, update: async (_id, update) => { updates.push(update); } }, { publish: async () => { throw new Error("queue offline"); } }),
    /queue offline/,
  );
  assert.deepEqual(updates, [{ status: "failed", progress: 100, errorCode: "queue_unavailable", errorMessage: "queue offline" }]);
});

test("submitRenderJob tolerates fallback scenes with unsupported character assets", async () => {
  const saved: any[] = [];
  const messages: any[] = [];
  const specSnapshot = { elements: [{ type: "character", asset: "https://example.com/character.blend", dialogue: { voice: "", lip_sync: "" } }] };
  await submitRenderJob({ id: "rj_3", workspaceId: "w_1", projectId: "p_1", shotId: "s_1", template: "interruption_spokescharacter_v1", templateVersion: 1, specSnapshot }, { create: async (value) => { saved.push(value); }, get: async () => null, update: async () => {} }, { publish: async (value) => { messages.push(value); } });
  assert.equal(saved.length, 1);
  assert.deepEqual(messages, [{ renderJobId: "rj_3" }]);
});

test("submitRenderJob tolerates legacy voice and lip sync values when speech is unavailable", async () => {
  const saved: any[] = [];
  const messages: any[] = [];
  const specSnapshot = { elements: [{ type: "character", dialogue: { text: "hello", voice: "alloy", lip_sync: "rhubarb" } }] };
  await submitRenderJob({ id: "rj_4", workspaceId: "w_1", projectId: "p_1", shotId: "s_1", template: "interruption_spokescharacter_v1", templateVersion: 1, specSnapshot }, { create: async (value) => { saved.push(value); }, get: async () => null, update: async () => {} }, { publish: async (value) => { messages.push(value); } });
  assert.equal(saved.length, 1);
  assert.deepEqual(messages, [{ renderJobId: "rj_4" }]);
});

test("validateRendererCapabilitiesForScene permits fallback and gates external worker character formats", () => {
  assert.doesNotThrow(() => validateRendererCapabilitiesForScene(
    { elements: [{ type: "character", asset: "https://example.com/character.gltf", dialogue: { voice: "", lip_sync: "" } }] },
    { character: false, speech: false, lipSync: false, characterFormats: [] },
  ));
  assert.doesNotThrow(() => validateRendererCapabilitiesForScene(
    { elements: [{ type: "character", asset: "https://example.com/character.gltf", dialogue: { voice: "", lip_sync: "" } }] },
    { character: true, speech: false, lipSync: false, characterFormats: [".blend", ".gltf"] },
  ));
  assert.throws(() => validateRendererCapabilitiesForScene(
    { elements: [{ type: "character", asset: "https://example.com/character.fbx", dialogue: { voice: "", lip_sync: "" } }] },
    { character: true, speech: false, lipSync: false, characterFormats: [".blend"] },
  ), /does not support this character file format/);
});
