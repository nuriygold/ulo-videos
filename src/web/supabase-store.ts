import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { AssetRecord, ControlPlaneStore } from "./integrations";

type Json = Record<string, unknown>;

export class SupabaseControlPlaneStore implements ControlPlaneStore {
  constructor(private readonly client: SupabaseClient) {}

  async createWorkspace(id: string) {
    const { error } = await this.client.from("workspaces").insert({ id });
    if (error && error.code !== "23505") throw error;
  }

  async createProject(input: { id: string; workspaceId: string; name: string }) {
    const { error } = await this.client.from("projects").insert({ id: input.id, workspace_id: input.workspaceId, name: input.name });
    if (error) throw error;
  }

  async projectBelongsToWorkspace(projectId: string, workspaceId: string) {
    const { data, error } = await this.client
      .from("projects")
      .select("id")
      .eq("id", projectId)
      .eq("workspace_id", workspaceId)
      .maybeSingle();
    if (error) throw error;
    return Boolean(data);
  }

  async saveAsset(input: AssetRecord) {
    const { error } = await this.client.from("assets").upsert({
      id: input.id,
      workspace_id: input.workspaceId,
      project_id: input.projectId ?? null,
      blob_key: input.blobKey,
      blob_url: input.blobUrl,
      role: input.role,
      mime_type: input.mimeType,
      bytes: input.bytes,
      sha256: input.sha256 ?? null,
    });
    if (error) throw error;
  }

  async saveShot(input: { id: string; projectId: string; name: string; template: string; templateVersion: number; spec: Json }) {
    const { error } = await this.client.from("shots").upsert({ id: input.id, project_id: input.projectId, name: input.name, template: input.template, template_version: input.templateVersion, spec: input.spec, updated_at: new Date().toISOString() });
    if (error) throw error;
  }

  async createRenderJob(input: { id: string; workspaceId: string; projectId: string; shotId: string; template: string; templateVersion: number; specSnapshot: Json }) {
    const { error } = await this.client.from("render_jobs").insert({ id: input.id, workspace_id: input.workspaceId, project_id: input.projectId, shot_id: input.shotId, template: input.template, template_version: input.templateVersion, spec_snapshot: input.specSnapshot, status: "queued", progress: 0, attempt: 1 });
    if (error) throw error;
  }

  async getRenderJob(id: string, workspaceId: string) {
    const { data, error } = await this.client.from("render_jobs").select("*").eq("id", id).eq("workspace_id", workspaceId).maybeSingle();
    if (error) throw error;
    return data;
  }

  async updateRenderJob(id: string, update: Json) {
    const { error } = await this.client.from("render_jobs").update(update).eq("id", id);
    if (error) throw error;
  }
}

export function getSupabaseStore(env: NodeJS.ProcessEnv = process.env) {
  const url = env.SUPABASE_URL;
  const key = env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) throw new Error("Cloud database is not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY");
  return new SupabaseControlPlaneStore(createClient(url, key, { auth: { autoRefreshToken: false, persistSession: false } }));
}
