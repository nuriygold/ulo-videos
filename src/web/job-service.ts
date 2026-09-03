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
  await queue.publish(createRenderJobMessage(job.id));
  return job;
}
