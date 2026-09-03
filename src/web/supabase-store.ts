import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { AssetRecord, ControlPlaneStore, ProjectRecord, ShotRecord } from "./integrations";
import { WorkspaceOwnershipError } from "./request-errors";

type Json = Record<string, unknown>;

function projectRecord(row: { id: string; workspace_id: string; name: string; created_at: string }): ProjectRecord {
  return { id: row.id, workspaceId: row.workspace_id, name: row.name, createdAt: row.created_at };
}

function shotRecord(row: { id: string; project_id: string; name: string; template: string; template_version: number; spec: Json; created_at: string; updated_at: string }): ShotRecord {
  return { id: row.id, projectId: row.project_id, name: row.name, template: row.template, templateVersion: row.template_version, spec: row.spec, createdAt: row.created_at, updatedAt: row.updated_at };
}

export class SupabaseControlPlaneStore implements ControlPlaneStore {
  constructor(private readonly client: SupabaseClient) {}

  async createWorkspace(id: string) {
    const { error } = await this.client.from("workspaces").insert({ id });
    if (error && error.code !== "23505") throw error;
  }

  async createProject(input: { id: string; workspaceId: string; name: string }) {
    const { data, error } = await this.client
      .from("projects")
      .insert({ id: input.id, workspace_id: input.workspaceId, name: input.name })
      .select("id,workspace_id,name,created_at")
      .single();
    if (error) throw error;
    return projectRecord(data);
  }

  async listProjects(workspaceId: string) {
    const { data, error } = await this.client
      .from("projects")
      .select("id,workspace_id,name,created_at")
      .eq("workspace_id", workspaceId)
      .order("created_at", { ascending: true });
    if (error) throw error;
    return (data ?? []).map(projectRecord);
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

  async getShotWorkspace(shotId: string) {
    const { data, error } = await this.client
      .from("shots")
      .select("projects!inner(workspace_id)")
      .eq("id", shotId)
      .maybeSingle();
    if (error) throw error;
    const projects = (data as { projects?: { workspace_id?: string } | Array<{ workspace_id?: string }> } | null)?.projects;
    return (Array.isArray(projects) ? projects[0]?.workspace_id : projects?.workspace_id) ?? null;
  }

  async saveAsset(input: AssetRecord) {
    const asset = {
      id: input.id,
      workspace_id: input.workspaceId,
      project_id: input.projectId ?? null,
      blob_key: input.blobKey,
      blob_url: input.blobUrl,
      role: input.role,
      mime_type: input.mimeType,
      bytes: input.bytes,
      sha256: input.sha256 ?? null,
    };
    const { error } = await this.client.from("assets").insert(asset);
    if (!error) return;
    if (error.code !== "23505") throw error;

    const { data: existing, error: lookupError } = await this.client
      .from("assets")
      .select("id,workspace_id,project_id,blob_key,blob_url,role,mime_type,bytes,sha256")
      .eq("id", input.id)
      .maybeSingle();
    if (lookupError) throw lookupError;

    const identical = existing
      && existing.id === asset.id
      && existing.workspace_id === asset.workspace_id
      && existing.project_id === asset.project_id
      && existing.blob_key === asset.blob_key
      && existing.blob_url === asset.blob_url
      && existing.role === asset.role
      && existing.mime_type === asset.mime_type
      && existing.bytes === asset.bytes
      && existing.sha256 === asset.sha256;
    if (!identical) throw new Error("asset ID conflicts with existing metadata");
  }

  async saveShot(input: { id: string; workspaceId: string; projectId: string; name: string; template: string; templateVersion: number; spec: Json }) {
    if (!await this.projectBelongsToWorkspace(input.projectId, input.workspaceId)) throw new WorkspaceOwnershipError("project not found in this workspace");
    const { data: existing, error: existingError } = await this.client
      .from("shots")
      .select("id,project_id,projects!inner(workspace_id)")
      .eq("id", input.id)
      .maybeSingle();
    if (existingError) throw existingError;
    const projectLink = (existing as { projects?: { workspace_id?: string } | Array<{ workspace_id?: string }> } | null)?.projects;
    const existingWorkspace = Array.isArray(projectLink) ? projectLink[0]?.workspace_id : projectLink?.workspace_id;
    if (existing && existingWorkspace !== input.workspaceId) throw new WorkspaceOwnershipError("shot ID belongs to another workspace");
    if (existing && existing.project_id !== input.projectId) throw new WorkspaceOwnershipError("shot cannot be reassigned to another project", 409);
    const values = { name: input.name, template: input.template, template_version: input.templateVersion, spec: input.spec, updated_at: new Date().toISOString() };
    const query = existing
      ? this.client.from("shots").update(values).eq("id", input.id).eq("project_id", input.projectId)
      : this.client.from("shots").insert({ id: input.id, project_id: input.projectId, ...values });
    const { data, error } = await query
      .select("id,project_id,name,template,template_version,spec,created_at,updated_at")
      .single();
    if (error) throw error;
    return shotRecord(data);
  }

  async listShots(projectId: string, workspaceId: string) {
    const { data, error } = await this.client
      .from("shots")
      .select("id,project_id,name,template,template_version,spec,created_at,updated_at,projects!inner(workspace_id)")
      .eq("project_id", projectId)
      .eq("projects.workspace_id", workspaceId)
      .order("created_at", { ascending: true });
    if (error) throw error;
    return (data ?? []).map(shotRecord);
  }

  async getShot(shotId: string, projectId: string, workspaceId: string) {
    const { data, error } = await this.client
      .from("shots")
      .select("id,project_id,name,template,template_version,spec,created_at,updated_at,projects!inner(workspace_id)")
      .eq("id", shotId)
      .eq("project_id", projectId)
      .eq("projects.workspace_id", workspaceId)
      .maybeSingle();
    if (error) throw error;
    return data ? shotRecord(data) : null;
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
