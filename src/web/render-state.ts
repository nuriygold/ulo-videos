import type { RenderStage } from "./contracts";

const NEXT_STAGES: Record<RenderStage, readonly RenderStage[]> = {
  queued: ["preparing", "failed"],
  preparing: ["downloading_assets", "failed"],
  downloading_assets: ["generating_audio", "building_scene", "failed"],
  generating_audio: ["lip_sync", "building_scene", "failed"],
  lip_sync: ["building_scene", "failed"],
  building_scene: ["rendering", "failed"],
  rendering: ["encoding", "failed"],
  encoding: ["uploading", "failed"],
  uploading: ["completed", "failed"],
  completed: [],
  failed: [],
};

export function isRenderTransitionAllowed(from: RenderStage, to: RenderStage): boolean {
  return NEXT_STAGES[from].includes(to);
}
