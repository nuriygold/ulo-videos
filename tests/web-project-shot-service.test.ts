import test from "node:test";
import assert from "node:assert/strict";
import {
  createProjectForWorkspace,
  getShotForWorkspace,
  listProjectsForWorkspace,
  listShotsForWorkspace,
  parseProjectInput,
  parseShotCreateInput,
  parseShotInput,
  saveShotForWorkspace,
} from "../src/web/project-shot-service";
import type { ControlPlaneStore, ProjectRecord, ShotRecord } from "../src/web/integrations";
import { SupabaseControlPlaneStore } from "../src/web/supabase-store";

const validScene = {
  template: "interruption_spokescharacter_v1",
  version: 1,
  source: { video: "assets/house-leak.mp4" },
  trigger: { type: "timestamp", value: 7.4 },
  background: { action: "freeze" },
  elements: [{
    id: "spokesperson",
    type: "character",
    asset: "assets/lizard.blend",
    position: "foreground_right",
    entrance: { type: "pop_in" },
    performance: { gesture: "shrug_and_point" },
    dialogue: { text: "Hi", voice: "voice_01", lip_sync: "rhubarb" },
  }],
  captions: { enabled: true, style: "lower_third" },
  branding: { logo: "assets/logo.svg" },
  continuation: { action: "resume" },
  output: { format: "mp4", width: 1920, height: 1080, fps: 30 },
};

class MemoryControlPlaneStore implements ControlPlaneStore {
  projects: ProjectRecord[] = [];
  shots: ShotRecord[] = [];

  async createWorkspace() {}

  async createProject(input: { id: string; workspaceId: string; name: string }) {
    const project = { ...input, createdAt: "2026-09-03T12:00:00.000Z" };
    this.projects.push(project);
    return project;
  }

  async listProjects(workspaceId: string) {
    return this.projects.filter((project) => project.workspaceId === workspaceId);
  }

  async projectBelongsToWorkspace(projectId: string, workspaceId: string) {
    return this.projects.some((project) => project.id === projectId && project.workspaceId === workspaceId);
  }

  async getShotWorkspace(shotId: string) {
    return this.shots.find((shot) => shot.id === shotId)?.projectId === "p_2" ? "ws_2" : this.shots.some((shot) => shot.id === shotId) ? "ws_1" : null;
  }

  async saveAsset() {}

  async saveShot(input: Omit<ShotRecord, "createdAt" | "updatedAt"> & { workspaceId: string }) {
    if (!await this.projectBelongsToWorkspace(input.projectId, input.workspaceId)) {
      throw new Error("project not found in this workspace");
    }
    const index = this.shots.findIndex((shot) => shot.id === input.id);
    const shot = {
      id: input.id,
      projectId: input.projectId,
      name: input.name,
      template: input.template,
      templateVersion: input.templateVersion,
      spec: structuredClone(input.spec),
      createdAt: index >= 0 ? this.shots[index].createdAt : "2026-09-03T12:00:00.000Z",
      updatedAt: "2026-09-03T12:00:00.000Z",
    };
    if (index >= 0) this.shots[index] = shot;
    else this.shots.push(shot);
    return shot;
  }

  async listShots(projectId: string, workspaceId: string) {
    if (!await this.projectBelongsToWorkspace(projectId, workspaceId)) return [];
    return this.shots.filter((shot) => shot.projectId === projectId);
  }

  async getShot(shotId: string, projectId: string, workspaceId: string) {
    if (!await this.projectBelongsToWorkspace(projectId, workspaceId)) return null;
    return this.shots.find((shot) => shot.id === shotId && shot.projectId === projectId) ?? null;
  }

  async createRenderJob() {}
  async listRenderJobs() { return []; }
  async getRenderJob() { return null; }
  async updateRenderJob() {}
}

test("project helpers trim names and list only the anonymous workspace", async () => {
  const store = new MemoryControlPlaneStore();
  store.projects.push({ id: "p_other", workspaceId: "ws_other", name: "Other", createdAt: "2026-09-03T11:00:00.000Z" });

  assert.deepEqual(parseProjectInput({ name: "  Launch film  " }), { name: "Launch film" });
  const created = await createProjectForWorkspace({ id: "p_1", workspaceId: "ws_1", name: "Launch film" }, store);
  assert.equal(created.workspaceId, "ws_1");
  assert.deepEqual(await listProjectsForWorkspace("ws_1", store), [created]);
});

test("project input rejects missing and oversized names", () => {
  assert.throws(() => parseProjectInput({}), /name/i);
  assert.throws(() => parseProjectInput({ name: " ".repeat(3) }), /name/i);
  assert.throws(() => parseProjectInput({ name: "x".repeat(121) }), /120/);
});

test("shot input accepts a valid deterministic Scene v1 snapshot", () => {
  assert.deepEqual(parseShotInput({
    name: "  Opening shot  ",
    template: "interruption_spokescharacter_v1",
    templateVersion: 1,
    spec: validScene,
  }), {
    name: "Opening shot",
    template: "interruption_spokescharacter_v1",
    templateVersion: 1,
    spec: validScene,
  });
});

test("shot input rejects malformed scenes and mismatched template metadata", () => {
  assert.throws(() => parseShotInput({ name: "Shot", template: validScene.template, spec: { ...validScene, output: { ...validScene.output, width: 0 } } }), /output\.width/i);
  assert.throws(() => parseShotInput({ name: "Shot", template: "other", spec: validScene }), /template/i);
  assert.throws(() => parseShotInput({ name: "Shot", template: validScene.template, templateVersion: 2, spec: validScene }), /version/i);
  assert.throws(() => parseShotInput({ name: "Shot", template: validScene.template, spec: { ...validScene, surprise: true } }), /surprise|property/i);
});

test("shot create input requires a project identifier and normalizes its scene snapshot", () => {
  assert.deepEqual(parseShotCreateInput({
    projectId: "p_1",
    name: "  Opening shot  ",
    template: validScene.template,
    spec: validScene,
  }), {
    projectId: "p_1",
    name: "Opening shot",
    template: validScene.template,
    templateVersion: 1,
    spec: validScene,
  });
  assert.throws(() => parseShotCreateInput({ name: "Opening shot", template: validScene.template, spec: validScene }), /projectId/i);
  assert.throws(() => parseShotCreateInput({ projectId: " ", name: "Opening shot", template: validScene.template, spec: validScene }), /projectId/i);
});

test("shot helpers save, list, and get only through the owning workspace", async () => {
  const store = new MemoryControlPlaneStore();
  store.projects.push(
    { id: "p_1", workspaceId: "ws_1", name: "Mine", createdAt: "2026-09-03T11:00:00.000Z" },
    { id: "p_2", workspaceId: "ws_2", name: "Other", createdAt: "2026-09-03T11:00:00.000Z" },
  );

  const saved = await saveShotForWorkspace({
    id: "s_1",
    workspaceId: "ws_1",
    projectId: "p_1",
    name: "Opening shot",
    template: validScene.template,
    templateVersion: 1,
    spec: validScene,
  }, store);

  assert.equal(saved.id, "s_1");
  assert.deepEqual(await listShotsForWorkspace("p_1", "ws_1", store), [saved]);
  assert.deepEqual(await getShotForWorkspace("s_1", "p_1", "ws_1", store), saved);
  assert.deepEqual(await listShotsForWorkspace("p_1", "ws_2", store), []);
  assert.equal(await getShotForWorkspace("s_1", "p_1", "ws_2", store), null);
  await assert.rejects(saveShotForWorkspace({ ...saved, workspaceId: "ws_2" }, store), /project/i);
});

test("Supabase saves shots with an ownership-scoped insert or update, never an upsert", async () => {
  const operations: Array<{ table: string; method: string; filters: Array<[string, unknown]> }> = [];
  let existing: Record<string, unknown> | null = null;
  const client = {
    from: (table: string) => {
      const operation = { table, method: "", filters: [] as Array<[string, unknown]> };
      operations.push(operation);
      const query = {
        insert: () => { operation.method = "insert"; return query; },
        update: () => { operation.method = "update"; return query; },
        select: () => { if (!operation.method) operation.method = "select"; return query; },
        eq: (key: string, value: unknown) => { operation.filters.push([key, value]); return query; },
        single: async () => ({ data: { id: "s_1", project_id: "p_1", name: "Opening shot", template: validScene.template, template_version: 1, spec: validScene, created_at: "2026-09-03T12:00:00.000Z", updated_at: "2026-09-03T12:00:01.000Z" }, error: null }),
        maybeSingle: async () => ({ data: table === "projects" ? { id: "p_1" } : existing, error: null }),
      };
      return query;
    },
  } as never;
  const store = new SupabaseControlPlaneStore(client);
  const input = { id: "s_1", workspaceId: "ws_1", projectId: "p_1", name: "Opening shot", template: validScene.template, templateVersion: 1, spec: validScene };

  await store.saveShot(input);
  existing = { id: "s_1", project_id: "p_1", projects: { workspace_id: "ws_1" } };
  await store.saveShot({ ...input, name: "Updated shot" });

  assert.equal(operations.some((operation) => operation.method === "upsert"), false);
  assert.deepEqual(operations.filter((operation) => operation.table === "shots").map((operation) => operation.method), ["select", "insert", "select", "update"]);
  assert.deepEqual(operations.filter((operation) => operation.table === "shots")[3].filters, [["id", "s_1"], ["project_id", "p_1"]]);
});

test("Supabase rejects a shot ID already owned by another workspace", async () => {
  const operations: Array<{ table: string; method: string }> = [];
  const client = {
    from: (table: string) => {
      const operation = { table, method: "" };
      operations.push(operation);
      const query = {
        insert: () => { operation.method = "insert"; return query; },
        update: () => { operation.method = "update"; return query; },
        select: () => { if (!operation.method) operation.method = "select"; return query; },
        eq: () => query,
        single: async () => ({ data: null, error: null }),
        maybeSingle: async () => ({ data: table === "projects" ? { id: "p_1" } : { id: "s_taken", project_id: "p_other", projects: { workspace_id: "ws_other" } }, error: null }),
      };
      return query;
    },
  } as never;
  const store = new SupabaseControlPlaneStore(client);

  await assert.rejects(store.saveShot({ id: "s_taken", workspaceId: "ws_1", projectId: "p_1", name: "Opening shot", template: validScene.template, templateVersion: 1, spec: validScene }), /workspace/i);
  assert.equal(operations.some((operation) => operation.table === "shots" && ["insert", "update", "upsert"].includes(operation.method)), false);
});

test("Supabase project and shot methods map camel-case records and keep queries workspace-scoped", async () => {
  const operations: Array<{ table: string; method: string; value?: unknown; filters: Array<[string, unknown]> }> = [];
  const client = {
    from: (table: string) => {
      const operation = { table, method: "", value: undefined as unknown, filters: [] as Array<[string, unknown]> };
      operations.push(operation);
      const query = {
        insert: (value: unknown) => {
          operation.method = "insert";
          operation.value = value;
          return query;
        },
        upsert: (value: unknown) => {
          operation.method = "upsert";
          operation.value = value;
          return query;
        },
        select: () => {
          if (!operation.method) operation.method = "select";
          return query;
        },
        eq: (key: string, value: unknown) => {
          operation.filters.push([key, value]);
          return query;
        },
        order: () => query,
        single: async () => ({
          data: operation.table === "projects"
            ? { id: "p_1", workspace_id: "ws_1", name: "Launch film", created_at: "2026-09-03T12:00:00.000Z" }
            : { id: "s_1", project_id: "p_1", name: "Opening shot", template: validScene.template, template_version: 1, spec: validScene, created_at: "2026-09-03T12:00:00.000Z", updated_at: "2026-09-03T12:00:01.000Z" },
          error: null,
        }),
        maybeSingle: async () => ({ data: operation.table === "projects" ? { id: "p_1" } : null, error: null }),
      };
      return query;
    },
  } as never;
  const store = new SupabaseControlPlaneStore(client);

  const project = await store.createProject({ id: "p_1", workspaceId: "ws_1", name: "Launch film" });
  await store.listProjects("ws_1");
  assert.equal(await store.projectBelongsToWorkspace("p_1", "ws_1"), true);
  const shot = await store.saveShot({ id: "s_1", workspaceId: "ws_1", projectId: "p_1", name: "Opening shot", template: validScene.template, templateVersion: 1, spec: validScene });
  await store.listShots("p_1", "ws_1");
  await store.getShot("s_1", "p_1", "ws_1");

  assert.deepEqual(project, { id: "p_1", workspaceId: "ws_1", name: "Launch film", createdAt: "2026-09-03T12:00:00.000Z" });
  assert.deepEqual(shot, { id: "s_1", projectId: "p_1", name: "Opening shot", template: validScene.template, templateVersion: 1, spec: validScene, createdAt: "2026-09-03T12:00:00.000Z", updatedAt: "2026-09-03T12:00:01.000Z" });
  assert.deepEqual(operations[0], {
    table: "projects",
    method: "insert",
    value: { id: "p_1", workspace_id: "ws_1", name: "Launch film" },
    filters: [],
  });
  assert.deepEqual(operations[1].filters, [["workspace_id", "ws_1"]]);
  assert.deepEqual(operations[2].filters, [["id", "p_1"], ["workspace_id", "ws_1"]]);
  assert.deepEqual(operations[4].filters, [["id", "s_1"]]);
  assert.deepEqual({
    ...operations[5],
    value: { ...(operations[5].value as Record<string, unknown>), updated_at: "timestamp" },
  }, {
    table: "shots",
    method: "insert",
    value: { id: "s_1", project_id: "p_1", name: "Opening shot", template: validScene.template, template_version: 1, spec: validScene, updated_at: "timestamp" },
    filters: [],
  });
  assert.match((operations[5].value as { updated_at: string }).updated_at, /^\d{4}-\d{2}-\d{2}T/);
  assert.deepEqual(operations[6].filters, [["project_id", "p_1"], ["projects.workspace_id", "ws_1"]]);
  assert.deepEqual(operations[7].filters, [["id", "s_1"], ["project_id", "p_1"], ["projects.workspace_id", "ws_1"]]);
});
