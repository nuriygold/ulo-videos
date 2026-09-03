import { NextResponse } from "next/server";
import { setupStatus } from "../../../src/web/setup-status";

export function GET() {
  return NextResponse.json(setupStatus(process.env));
}
