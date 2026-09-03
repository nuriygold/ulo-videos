import { createRenderJobMessage, type RenderJobMessage, type RenderStage } from "./contracts";

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

export async function submitRenderJob(input: Omit<RenderJob, "status" | "progress" | "attempt" | "specSnapshot"> & { specSnapshot: Record<string, unknown> }, repository: JobRepository, queue: RenderQueue): Promise<RenderJob> {
  const job: RenderJob = {
    ...input,
    specSnapshot: structuredClone(input.specSnapshot),
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
