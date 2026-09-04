import { createRenderJobMessage, type RenderJobMessage, type RenderStage } from "./contracts";
import { isCharacterUploadFormatSupported } from "./asset-upload";

export type RenderJob = {
  id: string;
  workspaceId: string;
  projectId: string;
  shotId: string;
  template: string;
  templateVersion: number;
  specSnapshot: Record<string, unknown>;
  status: RenderStage;
  progress: number;
  attempt: number;
};

export interface JobRepository {
  create(job: RenderJob): Promise<void>;
  get(id: string, workspaceId: string): Promise<RenderJob | null>;
  update(id: string, update: Partial<Pick<RenderJob, "status" | "progress">> & { errorCode?: string; errorMessage?: string }): Promise<void>;
}

export interface RenderQueue {
  publish(message: RenderJobMessage): Promise<void>;
}

type RenderCapabilityGate = {
  character?: boolean;
  speech?: boolean;
  lipSync?: boolean;
  characterFormats?: readonly string[];
};

const FALLBACK_RENDERER_CAPABILITIES: RenderCapabilityGate = { character: false, speech: false, lipSync: false, characterFormats: [] };

function hasValue(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function characterExtensionFromUrl(value: string): string {
  try {
    return new URL(value).pathname;
  } catch {
    return value;
  }
}

export function validateRendererCapabilitiesForScene(specSnapshot: Record<string, unknown>, capabilities: RenderCapabilityGate = FALLBACK_RENDERER_CAPABILITIES): void {
  const elements = Array.isArray(specSnapshot.elements) ? specSnapshot.elements : [];
  const character = elements.find((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && (item as Record<string, unknown>).type === "character"));
  if (!character) return;
  const asset = character.asset;
  if (hasValue(asset) && capabilities.character && !isCharacterUploadFormatSupported(characterExtensionFromUrl(asset), capabilities.characterFormats || [])) {
    throw new Error("The active renderer does not support this character file format.");
  }
}

export async function submitRenderJob(input: Omit<RenderJob, "status" | "progress" | "attempt" | "specSnapshot"> & { specSnapshot: Record<string, unknown> }, repository: JobRepository, queue: RenderQueue, capabilities: RenderCapabilityGate = FALLBACK_RENDERER_CAPABILITIES): Promise<RenderJob> {
  const specSnapshot = structuredClone(input.specSnapshot);
  validateRendererCapabilitiesForScene(specSnapshot, capabilities);
  const job: RenderJob = {
    ...input,
    specSnapshot,
    status: "queued",
    progress: 0,
    attempt: 1,
  };
  await repository.create(job);
  try {
    await queue.publish(createRenderJobMessage(job.id));
  } catch (error) {
    await repository.update(job.id, {
      status: "failed",
      progress: 100,
      errorCode: "queue_unavailable",
      errorMessage: error instanceof Error ? error.message : "render queue rejected the job",
    });
    throw error;
  }
  return job;
}
