import test from "node:test";
import assert from "node:assert/strict";
import { createProjectShotHandlers } from "../src/web/project-shot-routes";
import type { ControlPlaneStore, ProjectRecord, ShotRecord } from "../src/web/integrations";

const scene = {
  template: "interruption_spokescharacter_v1",
  version: 1,
  source: { video: "assets/source.mp4" },
  trigger: { type: "timestamp", value: 7.4 },
  background: { action: "freeze" },
  elements: [],
  captions: { enabled: false, style: "none" },
  branding: { logo: "assets/logo.svg" },
  continuation: { action: "resume" },
  output: { format: "mp4", width: 1920, height: 1080, fps: 30 },
};

class MemoryStore implements ControlPlaneStore {
  projects: ProjectRecord[] = [];
  shots: ShotRecord[] = [];
  failWith: Error | undefined;

  async createWorkspace() {}

  async createProject(input: { id: string; workspaceId: string; name: string }) {
    if (this.failWith) throw this.failWith;
    const project = { ...input, createdAt: "2026-09-03T12:00:00.000Z" };
    this.projects.push(project);
    return project;
  }

  async listProjects(workspaceId: string) {
    if (this.failWith) throw this.failWith;
    return this.projects.filter((project) => project.workspaceId === workspaceId);
  }

  async projectBelongsToWorkspace(projectId: string, workspaceId: string) {
    return this.projects.some((project) => project.id === projectId && project.workspaceId === workspaceId);
  }

  async getShotWorkspace(shotId: string) {
    const shot = this.shots.find((item) => item.id === shotId);
    return shot ? this.projects.find((project) => project.id === shot.projectId)?.workspaceId ?? null : null;
  }

  async saveAsset() {}

  async saveShot(input: Omit<ShotRecord, "createdAt" | "updatedAt"> & { workspaceId: string }) {
    if (this.failWith) throw this.failWith;
    if (!await this.projectBelongsToWorkspace(input.projectId, input.workspaceId)) throw new Error("project not found in this workspace");
    const existing = this.shots.find((shot) => shot.id === input.id);
    if (existing && existing.projectId !== input.projectId) throw new Error("shot cannot be reassigned to another project");
    const shot = { ...input, createdAt: existing?.createdAt ?? "2026-09-03T12:00:00.000Z", updatedAt: "2026-09-03T12:00:01.000Z" };
    this.shots = existing ? this.shots.map((item) => item.id === shot.id ? shot : item) : [...this.shots, shot];
    return shot;
  }

  async listShots(projectId: string, workspaceId: string) {
    if (this.failWith) throw this.failWith;
    if (!await this.projectBelongsToWorkspace(projectId, workspaceId)) return [];
    return this.shots.filter((shot) => shot.projectId === projectId);
  }

  async getShot(shotId: string, projectId: string, workspaceId: string) {
    if (this.failWith) throw this.failWith;
    if (!await this.projectBelongsToWorkspace(projectId, workspaceId)) return null;
    return this.shots.find((shot) => shot.id === shotId && shot.projectId === projectId) ?? null;
  }

  async createRenderJob() {}
  async getRenderJobById() { return null; }
  async listRenderJobs() { return []; }
  async getRenderJob() { return null; }
  async updateRenderJob() {}
}

function handlers(store: MemoryStore, workspaceId?: string) {
  return createProjectShotHandlers({
    getCookie: async () => workspaceId,
    getStore: () => store,
    newWorkspaceId: () => "ws_new",
    newProjectId: () => "pr_new",
    newShotId: () => "sh_new",
  });
}

async function json(response: Response) {
  return response.json() as Promise<Record<string, unknown>>;
}

test("project POST creates an anonymous workspace and sends its cookie", async () => {
  const store = new MemoryStore();
  const response = await handlers(store).createProject(new Request("http://ulo.test/api/projects", { method: "POST", body: JSON.stringify({ name: "Launch film" }) }));

  assert.equal(response.status, 201);
  assert.equal((await json(response)).project && store.projects[0].workspaceId, "ws_new");
  assert.match(response.headers.get("set-cookie") ?? "", /ulo_workspace=ws_new/);
  assert.equal(response.headers.get("set-cookie")?.includes("HttpOnly"), true);
});

test("project POST reuses an existing workspace without replacing its cookie", async () => {
  const store = new MemoryStore();
  const response = await handlers(store, "ws_existing").createProject(new Request("http://ulo.test/api/projects", { method: "POST", body: JSON.stringify({ name: "Second film" }) }));

  assert.equal(response.status, 201);
  assert.equal(store.projects[0].workspaceId, "ws_existing");
  assert.equal(response.headers.get("set-cookie"), null);
});

test("project GET has no-cookie empty state and hides other workspaces", async () => {
  const store = new MemoryStore();
  store.projects.push(
    { id: "pr_mine", workspaceId: "ws_mine", name: "Mine", createdAt: "2026-09-03T12:00:00.000Z" },
    { id: "pr_other", workspaceId: "ws_other", name: "Other", createdAt: "2026-09-03T12:00:00.000Z" },
  );

  const empty = await handlers(store).listProjects();
  const mine = await handlers(store, "ws_mine").listProjects();

  assert.deepEqual(await json(empty), { projects: [] });
  assert.deepEqual(await json(mine), { projects: [store.projects[0]] });
});

test("shot handlers require an established workspace to save but keep no-cookie reads anonymous", async () => {
  const store = new MemoryStore();
  const missing = await handlers(store).createShot(new Request("http://ulo.test/api/shots", { method: "POST", body: JSON.stringify({ projectId: "pr_1", name: "Opening", template: scene.template, spec: scene }) }));
  const list = await handlers(store).listOrGetShot(new Request("http://ulo.test/api/shots?projectId=pr_1"));
  const get = await handlers(store).listOrGetShot(new Request("http://ulo.test/api/shots?projectId=pr_1&shotId=sh_1"));

  assert.equal(missing.status, 400);
  assert.match(String((await json(missing)).error), /workspace/i);
  assert.deepEqual(await json(list), { shots: [] });
  assert.equal(get.status, 404);
});

test("shot handlers isolate workspaces and classify invalid, ownership, and persistence errors", async () => {
  const store = new MemoryStore();
  store.projects.push(
    { id: "pr_mine", workspaceId: "ws_mine", name: "Mine", createdAt: "2026-09-03T12:00:00.000Z" },
    { id: "pr_other", workspaceId: "ws_other", name: "Other", createdAt: "2026-09-03T12:00:00.000Z" },
  );
  store.shots.push({ id: "sh_other", projectId: "pr_other", name: "Other shot", template: scene.template, templateVersion: 1, spec: scene, createdAt: "2026-09-03T12:00:00.000Z", updatedAt: "2026-09-03T12:00:01.000Z" });

  const invalid = await handlers(store, "ws_mine").createShot(new Request("http://ulo.test/api/shots", { method: "POST", body: JSON.stringify({ projectId: "pr_mine", name: "Broken", template: scene.template, spec: { ...scene, output: { ...scene.output, width: 0 } } }) }));
  const foreign = await handlers(store, "ws_mine").createShot(new Request("http://ulo.test/api/shots", { method: "POST", body: JSON.stringify({ projectId: "pr_other", name: "Foreign", template: scene.template, spec: scene }) }));
  const hidden = await handlers(store, "ws_mine").listOrGetShot(new Request("http://ulo.test/api/shots?projectId=pr_other&shotId=sh_other"));
  store.failWith = new Error("database timeout");
  const unavailable = await handlers(store, "ws_mine").listProjects();

  assert.equal(invalid.status, 400);
  assert.equal(foreign.status, 404);
  assert.equal(hidden.status, 404);
  assert.equal(unavailable.status, 503);
});
