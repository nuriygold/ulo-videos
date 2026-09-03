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

function isSvgLogo(file: File): boolean { return file.type === "image/svg+xml" || file.name.toLowerCase().endsWith(".svg"); }

export async function rasterizeSvgLogo(file: File): Promise<File> {
  const imageUrl = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const next = new Image();
      next.onload = () => resolve(next); next.onerror = () => reject(new Error("SVG logo could not be rasterized.")); next.src = imageUrl;
    });
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth || image.width; canvas.height = image.naturalHeight || image.height;
    if (!canvas.width || !canvas.height) throw new Error("SVG logo has no drawable dimensions.");
    canvas.getContext("2d")?.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("SVG logo could not be converted to PNG.");
    return new File([blob], file.name.replace(/\.svg$/i, ".png"), { type: "image/png" });
  } finally { URL.revokeObjectURL(imageUrl); }
}

export async function fileForBrowserUpload(file: File, role: BrowserUploadRole, rasterize = rasterizeSvgLogo): Promise<File> {
  return role === "logo" && isSvgLogo(file) ? rasterize(file) : file;
}

export async function uploadAsset(file: File, workspaceId: string, projectId: string, role: BrowserUploadRole) {
  const body = await fileForBrowserUpload(file, role);
  const assetId = `a_${crypto.randomUUID()}`;
  const contentType = role === "character" ? "application/x-blender" : body.type;
  const intent = { assetId, workspaceId, projectId, role, filename: body.name };
  const pathname = buildAssetBlobKey(intent);
  const uploadBody = contentType && body.type !== contentType ? new File([body], body.name, { type: contentType }) : body;
  const blob = await upload(pathname, uploadBody, { access: "public", handleUploadUrl: "/api/assets/upload", clientPayload: JSON.stringify(intent), contentType, multipart: uploadBody.size > 25 * 1024 * 1024 });
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
