import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";
import { submitRenderJob } from "../../../src/web/job-service";
import { getSupabaseStore } from "../../../src/web/supabase-store";
import { newWorkspaceId, WORKSPACE_COOKIE } from "../../../src/web/anonymous-workspace";

export async function GET(request: Request) {
  const workspaceId = (await cookies()).get(WORKSPACE_COOKIE)?.value;
  if (!workspaceId) return NextResponse.json({ jobs: [] });
  try {
    const projectId = new URL(request.url).searchParams.get("projectId") || undefined;
    return NextResponse.json({ jobs: await getSupabaseStore().listRenderJobs(workspaceId, projectId) });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "render history is unavailable" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  if (!body || typeof body.projectId !== "string" || typeof body.shotId !== "string" || typeof body.template !== "string" || typeof body.specSnapshot !== "object" || !body.specSnapshot) return NextResponse.json({ error: "projectId, shotId, template, and specSnapshot are required" }, { status: 400 });
  try {
    const existing = (await cookies()).get(WORKSPACE_COOKIE)?.value;
    const workspaceId = existing || newWorkspaceId();
    const store = getSupabaseStore();
    await store.createWorkspace(workspaceId);
    const shot = await store.getShot(body.shotId, body.projectId, workspaceId);
    if (!shot) return NextResponse.json({ error: "shot not found in this workspace" }, { status: 404 });
    const job = await submitRenderJob({ id: `rj_${randomUUID()}`, workspaceId, projectId: body.projectId, shotId: body.shotId, template: shot.template, templateVersion: shot.templateVersion, specSnapshot: shot.spec }, { create: (value) => store.createRenderJob(value), get: (id) => store.getRenderJob(id, workspaceId) as any, update: (id, update) => store.updateRenderJob(id, { status: update.status, progress: update.progress, error_code: update.errorCode, error_message: update.errorMessage, completed_at: new Date().toISOString() }) }, { publish: async (message) => { const queueUrl = process.env.RENDER_QUEUE_URL; if (!queueUrl) throw new Error("render queue is not configured"); const response = await fetch(queueUrl, { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${process.env.RENDER_WORKER_SECRET || ""}` }, body: JSON.stringify(message) }); if (!response.ok) throw new Error(`render queue rejected the job (${response.status})`); } });
    const current = await store.getRenderJob(job.id, workspaceId);
    const response = NextResponse.json({ accepted: true, job: current ?? job }, { status: 202 });
    if (!existing) response.cookies.set(WORKSPACE_COOKIE, workspaceId, { httpOnly: true, sameSite: "lax", secure: true, maxAge: 60 * 60 * 24 * 30, path: "/" });
    return response;
  } catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "cloud render submission is not configured" }, { status: 503 }); }
}
