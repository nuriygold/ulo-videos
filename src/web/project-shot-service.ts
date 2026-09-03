import type { ControlPlaneStore, ProjectRecord, ShotRecord } from "./integrations";

type Json = Record<string, unknown>;

const POSITIONS = new Set(["foreground_left", "foreground_center", "foreground_right"]);
const ENTRANCES = new Set(["pop_in", "fade_in", "slide_left", "slide_right"]);
const GESTURES = new Set(["shrug_and_point", "wave", "nod", "talk_idle"]);
const CAPTION_STYLES = new Set(["none", "lower_third", "top", "center"]);

function object(value: unknown, field: string): Json {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${field} must be an object`);
  return value as Json;
}

function text(value: unknown, field: string) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${field} must be a non-empty string`);
  return value;
}

function positiveInteger(value: unknown, field: string) {
  if (!Number.isInteger(value) || (value as number) < 1) throw new Error(`${field} must be a positive integer`);
  return value as number;
}

function finiteNonNegativeNumber(value: unknown, field: string) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new Error(`${field} must be a finite non-negative number`);
  return value;
}

function choice(value: unknown, field: string, choices: Set<string>) {
  const parsed = text(value, field);
  if (!choices.has(parsed)) throw new Error(`${field} is not supported`);
  return parsed;
}

function onlyKeys(value: Json, field: string, keys: readonly string[]) {
  const allowed = new Set(keys);
  for (const key of Object.keys(value)) if (!allowed.has(key)) throw new Error(`${field}.${key} is not allowed`);
}

function normalizedScene(spec: Json): Json {
  onlyKeys(spec, "scene", ["template", "version", "source", "trigger", "background", "elements", "captions", "branding", "continuation", "output"]);
  text(spec.template, "template");
  if (spec.version !== 1) throw new Error("scene.version must be 1");
  const source = object(spec.source, "source");
  onlyKeys(source, "source", ["video"]);
  text(source.video, "source.video");
  const trigger = object(spec.trigger, "trigger");
  onlyKeys(trigger, "trigger", ["type", "value"]);
  if (trigger.type !== "timestamp") throw new Error("trigger.type must be timestamp");
  finiteNonNegativeNumber(trigger.value, "trigger.value");
  const background = object(spec.background, "background");
  onlyKeys(background, "background", ["action"]);
  if (background.action !== "freeze") throw new Error("background.action must be freeze");
  if (!Array.isArray(spec.elements)) throw new Error("elements must be a list");
  for (const [index, item] of spec.elements.entries()) {
    const prefix = `elements[${index}]`;
    const element = object(item, prefix);
    onlyKeys(element, prefix, ["id", "type", "asset", "position", "entrance", "performance", "dialogue"]);
    text(element.id, `${prefix}.id`);
    if (element.type !== "character") throw new Error(`${prefix}.type must be character`);
    text(element.asset, `${prefix}.asset`);
    choice(element.position, `${prefix}.position`, POSITIONS);
    const entrance = object(element.entrance, `${prefix}.entrance`);
    onlyKeys(entrance, `${prefix}.entrance`, ["type", "duration"]);
    choice(entrance.type, `${prefix}.entrance.type`, ENTRANCES);
    if (entrance.duration !== undefined && (typeof entrance.duration !== "number" || !Number.isFinite(entrance.duration) || entrance.duration <= 0)) throw new Error(`${prefix}.entrance.duration must be a positive number`);
    const performance = object(element.performance, `${prefix}.performance`);
    onlyKeys(performance, `${prefix}.performance`, ["gesture"]);
    choice(performance.gesture, `${prefix}.performance.gesture`, GESTURES);
    if (element.dialogue !== undefined) {
      const dialogue = object(element.dialogue, `${prefix}.dialogue`);
      onlyKeys(dialogue, `${prefix}.dialogue`, ["text", "voice", "lip_sync"]);
      text(dialogue.text, `${prefix}.dialogue.text`);
      text(dialogue.voice, `${prefix}.dialogue.voice`);
      text(dialogue.lip_sync, `${prefix}.dialogue.lip_sync`);
    }
  }
  const captions = object(spec.captions, "captions");
  onlyKeys(captions, "captions", ["enabled", "style"]);
  if (typeof captions.enabled !== "boolean") throw new Error("captions.enabled must be a boolean");
  choice(captions.style, "captions.style", CAPTION_STYLES);
  const branding = object(spec.branding, "branding");
  onlyKeys(branding, "branding", ["logo"]);
  text(branding.logo, "branding.logo");
  const continuation = object(spec.continuation, "continuation");
  onlyKeys(continuation, "continuation", ["action"]);
  if (continuation.action !== "resume") throw new Error("continuation.action must be resume");
  const output = object(spec.output, "output");
  onlyKeys(output, "output", ["format", "width", "height", "fps"]);
  if (output.format !== "mp4") throw new Error("output.format must be mp4");
  positiveInteger(output.width, "output.width");
  positiveInteger(output.height, "output.height");
  positiveInteger(output.fps, "output.fps");
  return structuredClone(spec);
}

function normalizeScene(spec: unknown): Json {
  const input = object(spec, "scene");
  if (input.version === 1 && "source" in input) return normalizedScene(input);
  const character = object(input.character, "scene.character");
  const dialogue = object(input.dialogue, "scene.dialogue");
  const branding = object(input.branding, "scene.branding");
  const output = object(input.output, "scene.output");
  if (!Array.isArray(output.resolution) || output.resolution.length !== 2) throw new Error("output.resolution must contain width and height");
  return normalizedScene({
    template: text(input.template, "template"), version: 1,
    source: { video: text(input.background_video, "source.video") },
    trigger: { type: "timestamp", value: finiteNonNegativeNumber(input.pause_at, "trigger.value") },
    background: { action: "freeze" },
    elements: [{ id: "spokesperson", type: "character", asset: text(character.asset, "elements[0].asset"), position: choice(character.position, "elements[0].position", POSITIONS), entrance: { type: choice(character.entrance, "elements[0].entrance.type", ENTRANCES) }, performance: { gesture: choice(character.gesture, "elements[0].performance.gesture", GESTURES) }, dialogue: { text: text(dialogue.text, "elements[0].dialogue.text"), voice: text(dialogue.voice, "elements[0].dialogue.voice"), lip_sync: text(dialogue.lip_sync, "elements[0].dialogue.lip_sync") } }],
    captions: { enabled: branding.caption_style !== "none", style: choice(branding.caption_style, "captions.style", CAPTION_STYLES) },
    branding: { logo: text(branding.logo, "branding.logo") }, continuation: { action: "resume" },
    output: { format: output.format ?? "mp4", width: output.resolution[0], height: output.resolution[1], fps: output.fps ?? 30 },
  });
}

export function parseProjectInput(value: unknown) {
  const body = object(value, "project");
  if (Object.keys(body).some((key) => key !== "name")) throw new Error("project contains an unsupported property");
  const name = text(body.name, "name").trim();
  if (name.length > 120) throw new Error("name must be at most 120 characters");
  return { name };
}

export function parseShotInput(value: unknown) {
  const body = object(value, "shot");
  if (Object.keys(body).some((key) => !["name", "template", "templateVersion", "spec"].includes(key))) throw new Error("shot contains an unsupported property");
  const name = text(body.name, "name").trim();
  if (name.length > 120) throw new Error("name must be at most 120 characters");
  const template = text(body.template, "template");
  const templateVersion = body.templateVersion === undefined ? 1 : positiveInteger(body.templateVersion, "templateVersion");
  const spec = normalizeScene(body.spec);
  if (spec.template !== template) throw new Error("template must match scene.template");
  if (spec.version !== templateVersion) throw new Error("templateVersion must match scene.version");
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
  if (!await store.projectBelongsToWorkspace(input.projectId, input.workspaceId)) throw new Error("project not found in this workspace");
  return store.saveShot({ ...input, spec: structuredClone(input.spec) });
}

export async function listShotsForWorkspace(projectId: string, workspaceId: string, store: ControlPlaneStore) {
  return store.listShots(projectId, workspaceId);
}

export async function getShotForWorkspace(shotId: string, projectId: string, workspaceId: string, store: ControlPlaneStore) {
  return store.getShot(shotId, projectId, workspaceId);
}
