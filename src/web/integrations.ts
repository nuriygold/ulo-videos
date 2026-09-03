/** Provider seams for the Vercel control plane. Implementations may use Neon,
 * Vercel Blob, and any queue without changing the shot editor or worker. */
export type AssetRole = "source_video" | "character" | "logo" | "audio" | "font" | "render_output";

export type AssetRecord = { id: string; workspaceId: string; projectId?: string; blobKey: string; blobUrl: string; role: AssetRole; mimeType: string; bytes: number; sha256?: string };

export interface BlobStore {
  createUploadUrl(input: { key: string; contentType: string; maxBytes: number }): Promise<{ uploadUrl: string; blobKey: string }>;
  createReadUrl(blobKey: string): Promise<string>;
  put(input: { key: string; body: Uint8Array; contentType: string }): Promise<{ url: string; key: string }>;
}

export interface ControlPlaneStore {
  createWorkspace(id: string): Promise<void>;
  createProject(input: { id: string; workspaceId: string; name: string }): Promise<void>;
  projectBelongsToWorkspace(projectId: string, workspaceId: string): Promise<boolean>;
  /** Insert an immutable asset claim; duplicate IDs must be rejected. */
  saveAsset(input: AssetRecord): Promise<void>;
  saveShot(input: { id: string; projectId: string; name: string; template: string; templateVersion: number; spec: Record<string, unknown> }): Promise<void>;
  createRenderJob(input: { id: string; workspaceId: string; projectId: string; shotId: string; template: string; templateVersion: number; specSnapshot: Record<string, unknown> }): Promise<void>;
  getRenderJob(id: string, workspaceId: string): Promise<Record<string, unknown> | null>;
  updateRenderJob(id: string, update: Record<string, unknown>): Promise<void>;
}

export interface RenderQueueProvider {
  publish(message: { renderJobId: string }): Promise<void>;
}

export function requiredCloudEnv(env: NodeJS.ProcessEnv = process.env) {
  const names = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "BLOB_READ_WRITE_TOKEN", "RENDER_QUEUE_URL", "RENDER_WORKER_SECRET"];
  return Object.fromEntries(names.map((name) => [name, Boolean(env[name])]));
}
