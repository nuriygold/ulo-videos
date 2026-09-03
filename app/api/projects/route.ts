import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";
import { newWorkspaceId, WORKSPACE_COOKIE } from "../../../src/web/anonymous-workspace";
import { createProjectShotHandlers } from "../../../src/web/project-shot-routes";
import { getSupabaseStore } from "../../../src/web/supabase-store";

const handlers = () => createProjectShotHandlers({
  getCookie: async () => (await cookies()).get(WORKSPACE_COOKIE)?.value,
  getStore: getSupabaseStore,
  newWorkspaceId,
  newProjectId: () => `pr_${randomUUID()}`,
  newShotId: () => `sh_${randomUUID()}`,
});

export async function GET() { return handlers().listProjects(); }
export async function POST(request: Request) { return handlers().createProject(request); }
