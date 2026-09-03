import type { ControlPlaneStore, ProjectRecord, ShotRecord } from "./integrations";
import { RequestValidationError, WorkspaceOwnershipError } from "./request-errors";
import { validateSceneV1 } from "./scene-contract";

type Json = Record<string, unknown>;

function object(value: unknown, field: string): Json {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new RequestValidationError(`${field} must be an object`);
  return value as Json;
}

function text(value: unknown, field: string) {
  if (typeof value !== "string" || !value.trim()) throw new RequestValidationError(`${field} must be a non-empty string`);
  return value;
}

function positiveInteger(value: unknown, field: string) {
  if (!Number.isInteger(value) || (value as number) < 1) throw new RequestValidationError(`${field} must be a positive integer`);
  return value as number;
}

function legacyScene(input: Json): Json {
  const character = object(input.character, "scene.character");
  const dialogue = object(input.dialogue, "scene.dialogue");
  const branding = object(input.branding, "scene.branding");
  const output = object(input.output, "scene.output");
  const resolution = Array.isArray(output.resolution) ? output.resolution : [];
  return {
    template: input.template,
    version: 1,
    source: { video: input.background_video },
    trigger: { type: "timestamp", value: input.pause_at },
    background: { action: "freeze" },
    elements: [{
      id: "spokesperson",
      type: "character",
      asset: character.asset,
      position: character.position,
      entrance: { type: character.entrance },
      performance: { gesture: character.gesture },
      dialogue: { text: dialogue.text, voice: dialogue.voice, lip_sync: dialogue.lip_sync },
    }],
    captions: { enabled: branding.caption_style !== "none", style: branding.caption_style },
    branding: { logo: branding.logo },
    continuation: { action: "resume" },
    output: { format: output.format ?? "mp4", width: resolution[0], height: resolution[1], fps: output.fps ?? 30 },
  };
}

function normalizeScene(spec: unknown): Json {
  const input = object(spec, "scene");
  return validateSceneV1(input.version === 1 && "source" in input ? input : legacyScene(input));
}

export function parseProjectInput(value: unknown) {
  const body = object(value, "project");
  if (Object.keys(body).some((key) => key !== "name")) throw new RequestValidationError("project contains an unsupported property");
  const name = text(body.name, "name").trim();
  if (name.length > 120) throw new RequestValidationError("name must be at most 120 characters");
  return { name };
}

export function parseShotInput(value: unknown) {
  const body = object(value, "shot");
  if (Object.keys(body).some((key) => !["name", "template", "templateVersion", "spec"].includes(key))) throw new RequestValidationError("shot contains an unsupported property");
  const name = text(body.name, "name").trim();
  if (name.length > 120) throw new RequestValidationError("name must be at most 120 characters");
  const template = text(body.template, "template");
  const templateVersion = body.templateVersion === undefined ? 1 : positiveInteger(body.templateVersion, "templateVersion");
  const spec = normalizeScene(body.spec);
  if (spec.template !== template) throw new RequestValidationError("template must match scene.template");
  if (spec.version !== templateVersion) throw new RequestValidationError("templateVersion must match scene.version");
  return { name, template, templateVersion, spec };
}

export function parseShotCreateInput(value: unknown) {
  const body = object(value, "shot");
  const { projectId, ...shot } = body;
  return { projectId: text(projectId, "projectId"), ...parseShotInput(shot) };
}

export async function createProjectForWorkspace(input: { id: string; workspaceId: string; name: string }, store: ControlPlaneStore): Promise<ProjectRecord> {
  return store.createProject(input);
}

export async function listProjectsForWorkspace(workspaceId: string, store: ControlPlaneStore) {
  return store.listProjects(workspaceId);
}

export async function saveShotForWorkspace(input: Omit<ShotRecord, "createdAt" | "updatedAt"> & { workspaceId: string }, store: ControlPlaneStore) {
  if (!await store.projectBelongsToWorkspace(input.projectId, input.workspaceId)) throw new WorkspaceOwnershipError("project not found in this workspace");
  return store.saveShot({ ...input, spec: structuredClone(input.spec) });
}

export async function listShotsForWorkspace(projectId: string, workspaceId: string, store: ControlPlaneStore) {
  return store.listShots(projectId, workspaceId);
}

export async function getShotForWorkspace(shotId: string, projectId: string, workspaceId: string, store: ControlPlaneStore) {
  return store.getShot(shotId, projectId, workspaceId);
}
