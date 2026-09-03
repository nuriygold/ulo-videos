export type InterruptionDraft = {
  shotName: string; sourceVideo: string; pauseAt: string; characterAsset: string;
  position: "foreground_left" | "foreground_center" | "foreground_right";
  entrance: "pop_in" | "fade_in" | "slide_left" | "slide_right";
  gesture: "shrug_and_point" | "wave" | "nod" | "talk_idle";
  dialogueText: string; voice: string; lipSync: string; captionsEnabled: boolean;
  captionStyle: "none" | "lower_third" | "top" | "center"; logo: string;
  width: string; height: string; fps: string;
};

export function buildInterruptionScene(draft: InterruptionDraft) {
  return { template: "interruption_spokescharacter_v1", version: 1, source: { video: draft.sourceVideo }, trigger: { type: "timestamp", value: Number(draft.pauseAt) }, background: { action: "freeze" }, elements: [{ id: "spokesperson", type: "character", asset: draft.characterAsset, position: draft.position, entrance: { type: draft.entrance }, performance: { gesture: draft.gesture }, dialogue: { text: draft.dialogueText, voice: draft.voice, lip_sync: draft.lipSync } }], captions: { enabled: draft.captionsEnabled, style: draft.captionStyle }, branding: { logo: draft.logo }, continuation: { action: "resume" }, output: { format: "mp4", width: Number(draft.width), height: Number(draft.height), fps: Number(draft.fps) } };
}

async function api<T>(url: string, body: unknown, request: typeof fetch = fetch): Promise<T> { const response = await request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); const data = await response.json() as T & { error?: string }; if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`); return data; }
export async function createProject(name: string, request = fetch) { return (await api<{ project: { id: string; name: string } }>("/api/projects", { name }, request)).project; }
export async function saveShot(projectId: string, name: string, spec: Record<string, unknown>, request = fetch) { return (await api<{ shot: { id: string; name: string } }>("/api/shots", { projectId, name, template: spec.template, templateVersion: spec.version, spec }, request)).shot; }
export async function submitRender(projectId: string, shotId: string, spec: Record<string, unknown>, request = fetch) { return (await api<{ job: { id: string; status: string; progress: number } }>("/api/render-jobs", { projectId, shotId, template: spec.template, templateVersion: spec.version, specSnapshot: spec }, request)).job; }
