import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { WORKSPACE_COOKIE } from "../../../src/web/anonymous-workspace";
import { getShotForWorkspace, listShotsForWorkspace, parseShotCreateInput, saveShotForWorkspace } from "../../../src/web/project-shot-service";
import { getSupabaseStore } from "../../../src/web/supabase-store";

function requiredIdentifier(value: string | null, field: string) {
  if (!value?.trim()) throw new Error(`${field} is required`);
  return value;
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const projectId = requiredIdentifier(url.searchParams.get("projectId"), "projectId");
    const shotId = url.searchParams.get("shotId");
    const workspaceId = (await cookies()).get(WORKSPACE_COOKIE)?.value;
    if (!workspaceId) {
      return shotId ? NextResponse.json({ error: "shot not found" }, { status: 404 }) : NextResponse.json({ shots: [] });
    }
    const store = getSupabaseStore();
    if (shotId) {
      const shot = await getShotForWorkspace(requiredIdentifier(shotId, "shotId"), projectId, workspaceId, store);
      return shot ? NextResponse.json({ shot }) : NextResponse.json({ error: "shot not found" }, { status: 404 });
    }
    return NextResponse.json({ shots: await listShotsForWorkspace(projectId, workspaceId, store) });
  } catch (error) {
    const message = error instanceof Error ? error.message : "shots are unavailable";
    const status = message.includes("required") ? 400 : 503;
    return NextResponse.json({ error: message }, { status });
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  try {
    const input = parseShotCreateInput(body);
    const workspaceId = (await cookies()).get(WORKSPACE_COOKIE)?.value;
    if (!workspaceId) return NextResponse.json({ error: "an anonymous workspace must be established before saving shots" }, { status: 400 });
    const shot = await saveShotForWorkspace({ id: `sh_${randomUUID()}`, workspaceId, ...input }, getSupabaseStore());
    return NextResponse.json({ shot }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "shot could not be saved";
    const status = message.includes("Cloud database is not configured") ? 503 : 400;
    return NextResponse.json({ error: message }, { status });
  }
}
