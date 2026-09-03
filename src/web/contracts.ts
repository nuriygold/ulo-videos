export const RENDER_STAGES = ["queued", "preparing", "downloading_assets", "generating_audio", "lip_sync", "building_scene", "rendering", "encoding", "uploading", "completed", "failed"] as const;
export type RenderStage = typeof RENDER_STAGES[number];

export type RenderJobMessage = { renderJobId: string };

export function createRenderJobMessage(renderJobId: string): RenderJobMessage {
  if (!renderJobId.trim()) throw new Error("renderJobId is required");
  return { renderJobId };
}
