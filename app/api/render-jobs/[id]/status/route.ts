import { NextResponse } from "next/server";
import { getSupabaseStore } from "../../../../../src/web/supabase-store";
import { RENDER_STAGES } from "../../../../../src/web/contracts";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const expected = process.env.RENDER_WORKER_SECRET;
  if (!expected || request.headers.get("authorization") !== `Bearer ${expected}`) return NextResponse.json({ error: "worker authorization required" }, { status: 401 });
  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  const { id } = await context.params;
  if (!body || typeof body.status !== "string" || !RENDER_STAGES.includes(body.status as never) || typeof body.progress !== "number" || !Number.isInteger(body.progress) || body.progress < 0 || body.progress > 100) return NextResponse.json({ error: "status and integer progress 0-100 are required" }, { status: 400 });
  try {
    const store = getSupabaseStore();
    const job = await store.getRenderJobById(id);
    if (!job) return NextResponse.json({ error: "render job not found" }, { status: 404 });
    const update: Record<string, unknown> = { status: body.status, progress: body.progress };
    if (typeof body.output_asset_id === "string") update.output_asset_id = body.output_asset_id;
    if (typeof body.error_code === "string") update.error_code = body.error_code;
    if (typeof body.error_message === "string") update.error_message = body.error_message;
    if (body.status === "completed" || body.status === "failed") update.completed_at = new Date().toISOString();
    await store.updateRenderJob(id, update);
    return NextResponse.json({ accepted: true, jobId: id, status: body.status, progress: body.progress });
  } catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "render job status could not be saved" }, { status: 503 }); }
}
