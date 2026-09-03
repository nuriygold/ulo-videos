import test from "node:test";
import assert from "node:assert/strict";
import {
  buildInterruptionScene,
  createProject,
  demoFileDescriptor,
  fileForBrowserUpload,
  saveShot,
  submitRender,
  type InterruptionDraft,
} from "../src/web/workspace-client";

const draft: InterruptionDraft = {
  shotName: "First interruption",
  sourceVideo: "https://example.com/source.mp4",
  pauseAt: "7.4",
  characterAsset: "https://example.com/character.blend",
  position: "foreground_right",
  entrance: "slide_left",
  gesture: "shrug_and_point",
  dialogueText: "Wait — there is a clearer way.",
  voice: "",
  lipSync: "",
  captionsEnabled: true,
  captionStyle: "lower_third",
  logo: "https://example.com/logo.svg",
  width: "1920",
  height: "1080",
  fps: "30",
};

test("buildInterruptionScene maps editor state to the deterministic Scene v1 contract", () => {
  assert.deepEqual(buildInterruptionScene(draft), {
    template: "interruption_spokescharacter_v1",
    version: 1,
    source: { video: "https://example.com/source.mp4" },
    trigger: { type: "timestamp", value: 7.4 },
    background: { action: "freeze" },
    elements: [{
      id: "spokesperson",
      type: "character",
      asset: "https://example.com/character.blend",
      position: "foreground_right",
      entrance: { type: "slide_left" },
      performance: { gesture: "shrug_and_point" },
      dialogue: { text: "Wait — there is a clearer way.", voice: "", lip_sync: "" },
    }],
    captions: { enabled: true, style: "lower_third" },
    branding: { logo: "https://example.com/logo.svg" },
    continuation: { action: "resume" },
    output: { format: "mp4", width: 1920, height: 1080, fps: 30 },
  });
});

test("workspace API helpers use the project, shot, and render contracts in order", async () => {
  const calls: Array<{ url: string; body: unknown }> = [];
  const responses = [
    { project: { id: "pr_1", name: "Launch film" } },
    { shot: { id: "sh_1", projectId: "pr_1", name: draft.shotName } },
    { accepted: true, job: { id: "rj_1", status: "queued", progress: 0 } },
  ];
  const request = async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), body: JSON.parse(String(init?.body)) });
    return Response.json(responses.shift(), { status: calls.length === 3 ? 202 : 201 });
  };

  const project = await createProject("Launch film", request);
  const scene = buildInterruptionScene(draft);
  const shot = await saveShot(project.id, draft.shotName, scene, request);
  const job = await submitRender(project.id, shot.id, scene, request);

  assert.deepEqual(calls, [
    { url: "/api/projects", body: { name: "Launch film" } },
    { url: "/api/shots", body: { projectId: "pr_1", name: draft.shotName, template: scene.template, templateVersion: 1, spec: scene } },
    { url: "/api/render-jobs", body: { projectId: "pr_1", shotId: "sh_1", template: scene.template, templateVersion: 1, specSnapshot: scene } },
  ]);
  assert.equal(job.status, "queued");
});

test("workspace API helpers surface server errors to the editor", async () => {
  const request = async () => Response.json({ error: "render queue is not configured" }, { status: 503 });
  await assert.rejects(createProject("Launch film", request), /render queue is not configured/);
});

test("demo file descriptors point at bundled assets with the correct upload MIME", () => {
  assert.deepEqual(demoFileDescriptor("source_video"), { url: "/demo/demo-source.mp4", filename: "demo-source.mp4", mimeType: "video/mp4" });
  assert.deepEqual(demoFileDescriptor("character"), { url: "/demo/demo-character.blend", filename: "demo-character.blend", mimeType: "application/x-blender" });
  assert.deepEqual(demoFileDescriptor("logo"), { url: "/demo/demo-logo.svg", filename: "demo-logo.svg", mimeType: "image/svg+xml" });
});

test("browser uploads rasterize SVG logos but preserve every other upload", async () => {
  const svg = { name: "brand.svg", type: "image/svg+xml" } as File;
  const png = { name: "brand.png", type: "image/png" } as File;
  let rasterized: File | undefined;

  assert.equal(await fileForBrowserUpload(svg, "logo", async (file) => {
    rasterized = file;
    return png;
  }), png);
  assert.equal(rasterized, svg);
  assert.equal(await fileForBrowserUpload(png, "logo", async () => { throw new Error("PNG must not be rasterized"); }), png);
  assert.equal(await fileForBrowserUpload(svg, "source_video", async () => { throw new Error("only logos are rasterized"); }), svg);
});
