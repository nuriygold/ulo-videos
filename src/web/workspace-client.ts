export type InterruptionDraft = {
  shotName: string; sourceVideo: string; pauseAt: string; characterAsset: string;
  position: "foreground_left" | "foreground_center" | "foreground_right";
  entrance: "pop_in" | "fade_in" | "slide_left" | "slide_right";
  gesture: "shrug_and_point" | "wave" | "nod" | "talk_idle";
  dialogueText: string; voice: string; lipSync: string; captionsEnabled: boolean;
  captionStyle: "none" | "lower_third" | "top" | "center"; logo: string;
  width: string; height: string; fps: string;
};

import { upload } from "@vercel/blob/client";
import { buildAssetBlobKey, type BrowserUploadRole } from "./asset-upload";

export type DemoFileRole = "source_video" | "character" | "logo";

export function demoFileDescriptor(role: DemoFileRole) {
  const files = {
    source_video: { url: "/demo/demo-source.mp4", filename: "demo-source.mp4", mimeType: "video/mp4" },
    character: { url: "/demo/demo-character.blend", filename: "demo-character.blend", mimeType: "application/x-blender" },
    logo: { url: "/demo/demo-logo.svg", filename: "demo-logo.svg", mimeType: "image/svg+xml" },
  } as const;
  return files[role];
}

export async function loadDemoFile(role: DemoFileRole, request: typeof fetch = fetch) {
  const descriptor = demoFileDescriptor(role);
  const response = await request(descriptor.url);
  if (!response.ok) throw new Error(`Demo ${role.replace("_", " ")} could not be loaded.`);
  return new File([await response.blob()], descriptor.filename, { type: descriptor.mimeType });
}

export async function uploadAsset(file: File, workspaceId: string, projectId: string, role: BrowserUploadRole) {
  const assetId = `a_${crypto.randomUUID()}`;
  const contentType = role === "character" ? "application/x-blender" : file.type;
  const intent = { assetId, workspaceId, projectId, role, filename: file.name };
  const pathname = buildAssetBlobKey(intent);
  const body = contentType && file.type !== contentType ? new File([file], file.name, { type: contentType }) : file;
  const blob = await upload(pathname, body, { access: "public", handleUploadUrl: "/api/assets/upload", clientPayload: JSON.stringify(intent), contentType, multipart: file.size > 25 * 1024 * 1024 });
  return blob.url;
}

export function buildInterruptionScene(draft: InterruptionDraft) {
  return { template: "interruption_spokescharacter_v1", version: 1, source: { video: draft.sourceVideo }, trigger: { type: "timestamp", value: Number(draft.pauseAt) }, background: { action: "freeze" }, elements: [{ id: "spokesperson", type: "character", asset: draft.characterAsset, position: draft.position, entrance: { type: draft.entrance }, performance: { gesture: draft.gesture }, dialogue: { text: draft.dialogueText, voice: draft.voice, lip_sync: draft.lipSync } }], captions: { enabled: draft.captionsEnabled, style: draft.captionStyle }, branding: { logo: draft.logo }, continuation: { action: "resume" }, output: { format: "mp4", width: Number(draft.width), height: Number(draft.height), fps: Number(draft.fps) } };
}

async function api<T>(url: string, body: unknown, request: typeof fetch = fetch): Promise<T> { const response = await request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); const data = await response.json() as T & { error?: string }; if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`); return data; }
async function get<T>(url: string, request: typeof fetch = fetch): Promise<T> { const response = await request(url); const data = await response.json() as T & { error?: string }; if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`); return data; }
export async function createProject(name: string, request = fetch) { return (await api<{ project: { id: string; name: string; workspaceId: string } }>("/api/projects", { name }, request)).project; }
export async function listProjects(request = fetch) { return (await get<{ projects: Array<{ id: string; name: string; workspaceId: string }> }>("/api/projects", request)).projects; }
export async function listRenderJobs(projectId: string | undefined, request = fetch) { return (await get<{ jobs: Array<{ id: string; status: string; progress: number; output_asset_id?: string; output_url?: string; error_message?: string }> }>(`/api/render-jobs${projectId ? `?projectId=${encodeURIComponent(projectId)}` : ""}`, request)).jobs; }
export async function saveShot(projectId: string, name: string, spec: Record<string, unknown>, request = fetch) { return (await api<{ shot: { id: string; name: string } }>("/api/shots", { projectId, name, template: spec.template, templateVersion: spec.version, spec }, request)).shot; }
export async function submitRender(projectId: string, shotId: string, spec: Record<string, unknown>, request = fetch) { return (await api<{ job: { id: string; status: string; progress: number; output_asset_id?: string; output_url?: string; error_message?: string } }>("/api/render-jobs", { projectId, shotId, template: spec.template, templateVersion: spec.version, specSnapshot: spec }, request)).job; }
