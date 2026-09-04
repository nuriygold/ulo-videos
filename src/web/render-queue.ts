export type RenderQueueMessage = { renderJobId: string };

export function authorizeQueueRequest(request: Request, expectedSecret: string | undefined) {
  return Boolean(expectedSecret && request.headers.get("authorization") === `Bearer ${expectedSecret}`);
}

export async function queueMessageFromRequest(request: Request): Promise<RenderQueueMessage> {
  const body = await request.json().catch(() => null) as { renderJobId?: unknown } | null;
  if (!body || typeof body.renderJobId !== "string" || !/^rj_[A-Za-z0-9_-]{1,120}$/.test(body.renderJobId)) throw new Error("renderJobId is required");
  return { renderJobId: body.renderJobId };
}

export function queueRejectionMessage(status: number, body: string): string {
  const detail = body.replace(/Bearer\s+[A-Za-z0-9._~+/-]+=*/g, "Bearer [redacted]").slice(0, 1000).trim();
  return `render queue rejected the job (${status})${detail ? `: ${detail}` : ""}`;
}
