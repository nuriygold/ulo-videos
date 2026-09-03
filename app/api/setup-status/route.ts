import { NextResponse } from "next/server";
import { rendererHealthForQueue, setupStatus } from "../../../src/web/setup-status";

export async function GET() {
  return NextResponse.json(setupStatus(process.env, await rendererHealthForQueue(process.env.RENDER_QUEUE_URL)));
}
