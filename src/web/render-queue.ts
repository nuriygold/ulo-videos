export type RenderQueueMessage = { renderJobId: string };

const MAX_QUEUE_ERROR_LENGTH = 480;

export function authorizeQueueRequest(request: Request, expectedSecret: string | undefined) {
  return Boolean(expectedSecret && request.headers.get("authorization") === `Bearer ${expectedSecret}`);
}

export async function queueMessageFromRequest(request: Request): Promise<RenderQueueMessage> {
  const body = await request.json().catch(() => null) as { renderJobId?: unknown } | null;
  if (!body || typeof body.renderJobId !== "string" || !/^rj_[A-Za-z0-9_-]{1,120}$/.test(body.renderJobId)) throw new Error("renderJobId is required");
  return { renderJobId: body.renderJobId };
}

export function queueRejectionMessage(status: number, body: string): string {
  let detail = body.trim();
  try {
    const parsed = JSON.parse(detail) as { error?: unknown };
    if (parsed && typeof parsed.error === "string") detail = parsed.error;
  } catch {
    // Preserve useful diagnostics when a dispatcher returns plain text.
  }
  const lines = detail.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.some((line) => /^(ffmpeg version|built with|configuration:|libav(?:util|codec|format|device))/i.test(line))) {
    detail = lines.slice(-3).join(" ");
  }
  detail = detail.replace(/Bearer\s+[A-Za-z0-9._~+/-]+=*/g, "Bearer [redacted]").replace(/\s+/g, " ").trim();
  if (detail.length > MAX_QUEUE_ERROR_LENGTH) detail = `…${detail.slice(-MAX_QUEUE_ERROR_LENGTH)}`;
  return `render queue rejected the job (${status})${detail ? `: ${detail}` : ""}`;
}
