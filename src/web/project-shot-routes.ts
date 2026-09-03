import type { ControlPlaneStore } from "./integrations";
import { ClientRequestError, RequestValidationError } from "./request-errors";
import { createProjectForWorkspace, getShotForWorkspace, listProjectsForWorkspace, listShotsForWorkspace, parseProjectInput, parseShotCreateInput, saveShotForWorkspace } from "./project-shot-service";

const WORKSPACE_COOKIE = "ulo_workspace";
const cookieAttributes = "HttpOnly; Path=/; Max-Age=2592000; SameSite=Lax; Secure";

type Dependencies = {
  getCookie: () => Promise<string | undefined>;
  getStore: () => ControlPlaneStore;
  newWorkspaceId: () => string;
  newProjectId: () => string;
  newShotId: () => string;
};

function json(value: unknown, init?: ResponseInit) { return Response.json(value, init); }

function errorResponse(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message : fallback;
  return json({ error: message }, { status: error instanceof ClientRequestError ? error.status : 503 });
}

function requiredIdentifier(value: string | null, field: string) {
  if (!value?.trim()) throw new RequestValidationError(`${field} is required`);
  return value;
}

export function createProjectShotHandlers(dependencies: Dependencies) {
  return {
    async listProjects() {
      const workspaceId = await dependencies.getCookie();
      if (!workspaceId) return json({ projects: [] });
      try { return json({ projects: await listProjectsForWorkspace(workspaceId, dependencies.getStore()) }); }
      catch (error) { return errorResponse(error, "projects are unavailable"); }
    },
    async createProject(request: Request) {
      const body = await request.json().catch(() => null);
      try {
        const input = parseProjectInput(body);
        const existingWorkspaceId = await dependencies.getCookie();
        const workspaceId = existingWorkspaceId ?? dependencies.newWorkspaceId();
        const store = dependencies.getStore();
        await store.createWorkspace(workspaceId);
        const project = await createProjectForWorkspace({ id: dependencies.newProjectId(), workspaceId, ...input }, store);
        const response = json({ project }, { status: 201 });
        if (!existingWorkspaceId) response.headers.set("Set-Cookie", `${WORKSPACE_COOKIE}=${encodeURIComponent(workspaceId)}; ${cookieAttributes}`);
        return response;
      } catch (error) { return errorResponse(error, "project could not be saved"); }
    },
    async listOrGetShot(request: Request) {
      try {
        const url = new URL(request.url);
        const projectId = requiredIdentifier(url.searchParams.get("projectId"), "projectId");
        const shotId = url.searchParams.get("shotId");
        const workspaceId = await dependencies.getCookie();
        if (!workspaceId) return shotId ? json({ error: "shot not found" }, { status: 404 }) : json({ shots: [] });
        const store = dependencies.getStore();
        if (shotId) {
          const shot = await getShotForWorkspace(requiredIdentifier(shotId, "shotId"), projectId, workspaceId, store);
          return shot ? json({ shot }) : json({ error: "shot not found" }, { status: 404 });
        }
        return json({ shots: await listShotsForWorkspace(projectId, workspaceId, store) });
      } catch (error) { return errorResponse(error, "shots are unavailable"); }
    },
    async createShot(request: Request) {
      const body = await request.json().catch(() => null);
      try {
        const input = parseShotCreateInput(body);
        const workspaceId = await dependencies.getCookie();
        if (!workspaceId) throw new RequestValidationError("an anonymous workspace must be established before saving shots");
        const shot = await saveShotForWorkspace({ id: dependencies.newShotId(), workspaceId, ...input }, dependencies.getStore());
        return json({ shot }, { status: 201 });
      } catch (error) { return errorResponse(error, "shot could not be saved"); }
    },
  };
}
