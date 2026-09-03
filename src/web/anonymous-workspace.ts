import { randomUUID } from "node:crypto";

export const WORKSPACE_COOKIE = "ulo_workspace";

export function newWorkspaceId() {
  return `ws_${randomUUID()}`;
}
