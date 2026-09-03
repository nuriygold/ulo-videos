import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { newWorkspaceId, WORKSPACE_COOKIE } from "../../../src/web/anonymous-workspace";
import { createProjectForWorkspace, listProjectsForWorkspace, parseProjectInput } from "../../../src/web/project-shot-service";
import { getSupabaseStore } from "../../../src/web/supabase-store";

const cookieOptions = { httpOnly: true, sameSite: "lax" as const, secure: true, maxAge: 60 * 60 * 24 * 30, path: "/" };

export async function GET() {
  const workspaceId = (await cookies()).get(WORKSPACE_COOKIE)?.value;
  if (!workspaceId) return NextResponse.json({ projects: [] });
  try {
    return NextResponse.json({ projects: await listProjectsForWorkspace(workspaceId, getSupabaseStore()) });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "projects are unavailable" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  try {
    const input = parseProjectInput(body);
    const cookieStore = await cookies();
    const existingWorkspaceId = cookieStore.get(WORKSPACE_COOKIE)?.value;
    const workspaceId = existingWorkspaceId ?? newWorkspaceId();
    const store = getSupabaseStore();
    await store.createWorkspace(workspaceId);
    const project = await createProjectForWorkspace({ id: `pr_${randomUUID()}`, workspaceId, ...input }, store);
    const response = NextResponse.json({ project }, { status: 201 });
    if (!existingWorkspaceId) response.cookies.set(WORKSPACE_COOKIE, workspaceId, cookieOptions);
    return response;
  } catch (error) {
    const message = error instanceof Error ? error.message : "project could not be saved";
    const status = message.includes("Cloud database is not configured") ? 503 : 400;
    return NextResponse.json({ error: message }, { status });
  }
}
