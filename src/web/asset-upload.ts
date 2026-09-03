import type { AssetRecord, AssetRole } from "./integrations";

const MIB = 1024 * 1024;
const GIB = 1024 * MIB;

export type BrowserUploadRole = Exclude<AssetRole, "render_output">;

export type AssetUploadIntent = {
  assetId: string;
  workspaceId: string;
  projectId?: string;
  role: BrowserUploadRole;
  filename: string;
};

export type AssetUploadPolicy = {
  allowedContentTypes: readonly string[];
  maximumSizeInBytes: number;
};

const UPLOAD_POLICIES: Record<BrowserUploadRole, AssetUploadPolicy> = {
  source_video: {
    allowedContentTypes: ["video/mp4", "video/quicktime", "video/webm"],
    maximumSizeInBytes: 5 * GIB,
  },
  character: {
    allowedContentTypes: ["application/x-blender"],
    maximumSizeInBytes: 2 * GIB,
  },
  logo: {
    allowedContentTypes: ["image/png", "image/jpeg", "image/webp", "image/svg+xml"],
    maximumSizeInBytes: 25 * MIB,
  },
  audio: {
    allowedContentTypes: ["audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/x-wav"],
    maximumSizeInBytes: 500 * MIB,
  },
  font: {
    allowedContentTypes: ["font/ttf", "font/otf", "font/woff", "font/woff2", "application/vnd.ms-opentype"],
    maximumSizeInBytes: 25 * MIB,
  },
};

const SCOPE_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

function requireScopeId(value: unknown, field: string): string {
  if (typeof value !== "string" || !SCOPE_ID.test(value)) {
    throw new Error(`${field} must be a safe scope identifier`);
  }
  return value;
}

function safeFilename(value: unknown): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 180) {
    throw new Error("filename must be between 1 and 180 characters");
  }
  if (value.includes("/") || value.includes("\\") || value.includes("\0") || value === "." || value === "..") {
    throw new Error("filename must not contain a path");
  }
  const normalized = value
    .normalize("NFKC")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^A-Za-z0-9._-]/g, "-")
    .replace(/-+/g, "-");
  if (!normalized || normalized === "." || normalized === "..") {
    throw new Error("filename does not contain a safe name");
  }
  return normalized;
}

function validateFilenameForRole(role: BrowserUploadRole, filename: string): void {
  if (role === "character" && !filename.toLowerCase().endsWith(".blend")) {
    throw new Error("character assets must use a .blend filename");
  }
}

export function uploadPolicyForRole(role: AssetRole): AssetUploadPolicy {
  if (role === "render_output") {
    throw new Error("render_output is worker-only and cannot be uploaded from a browser");
  }
  if (!Object.hasOwn(UPLOAD_POLICIES, role)) {
    throw new Error("role is not allowed for browser uploads");
  }
  return UPLOAD_POLICIES[role as BrowserUploadRole];
}

export function buildAssetBlobKey(intent: AssetUploadIntent): string {
  const workspaceId = requireScopeId(intent.workspaceId, "workspaceId");
  const projectScope = intent.projectId
    ? `projects/${requireScopeId(intent.projectId, "projectId")}`
    : "workspace-assets";
  const assetId = requireScopeId(intent.assetId, "assetId");
  uploadPolicyForRole(intent.role);
  const filename = safeFilename(intent.filename);
  validateFilenameForRole(intent.role, filename);
  return `workspaces/${workspaceId}/${projectScope}/${intent.role}/${assetId}/${filename}`;
}

export function parseAssetUploadIntent(payload: string | null): AssetUploadIntent {
  let value: unknown;
  try {
    value = payload ? JSON.parse(payload) : null;
  } catch {
    throw new Error("client payload must be valid JSON");
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("client payload must be an object");
  }
  const input = value as Record<string, unknown>;
  const assetId = requireScopeId(input.assetId, "assetId");
  const workspaceId = requireScopeId(input.workspaceId, "workspaceId");
  const role = input.role;
  if (typeof role !== "string") throw new Error("role is required");
  uploadPolicyForRole(role as AssetRole);
  const parsed: AssetUploadIntent = {
    assetId,
    workspaceId,
    role: role as BrowserUploadRole,
    filename: typeof input.filename === "string" ? input.filename : "",
  };
  safeFilename(parsed.filename);
  if (input.projectId !== undefined && input.projectId !== null) {
    parsed.projectId = requireScopeId(input.projectId, "projectId");
  }
  buildAssetBlobKey(parsed);
  return parsed;
}

export async function authorizeAssetUpload(input: {
  requestWorkspaceId: string | undefined;
  pathname: string;
  clientPayload: string | null;
  projectBelongsToWorkspace?: (projectId: string, workspaceId: string) => Promise<boolean>;
}): Promise<{ intent: AssetUploadIntent; policy: AssetUploadPolicy }> {
  if (!input.requestWorkspaceId) {
    throw new Error("an anonymous workspace must be established before uploading assets");
  }
  const intent = parseAssetUploadIntent(input.clientPayload);
  if (intent.workspaceId !== input.requestWorkspaceId) {
    throw new Error("the upload workspace does not match this browser workspace");
  }
  if (intent.projectId) {
    if (!input.projectBelongsToWorkspace) throw new Error("project ownership cannot be verified");
    if (!await input.projectBelongsToWorkspace(intent.projectId, input.requestWorkspaceId)) {
      throw new Error("the upload project does not belong to this browser workspace");
    }
  }
  if (input.pathname !== buildAssetBlobKey(intent)) {
    throw new Error("the requested pathname does not match the scoped asset key");
  }
  return { intent, policy: uploadPolicyForRole(intent.role) };
}

export function assetRecordFromUpload(input: {
  intent: AssetUploadIntent;
  blob: { pathname: string; url: string; contentType: string };
  bytes: number;
}): AssetRecord {
  const expectedPathname = buildAssetBlobKey(input.intent);
  if (input.blob.pathname !== expectedPathname) {
    throw new Error("completed upload pathname does not match its scoped asset key");
  }
  const policy = uploadPolicyForRole(input.intent.role);
  const contentType = input.blob.contentType.toLowerCase().split(";", 1)[0].trim();
  if (!policy.allowedContentTypes.includes(contentType)) {
    throw new Error(`completed upload content type is not allowed for ${input.intent.role}`);
  }
  if (!Number.isSafeInteger(input.bytes) || input.bytes <= 0 || input.bytes > policy.maximumSizeInBytes) {
    throw new Error("completed upload size is outside the allowed range");
  }
  let url: URL;
  try {
    url = new URL(input.blob.url);
  } catch {
    throw new Error("completed upload URL is invalid");
  }
  if (url.protocol !== "https:") throw new Error("completed upload URL must use HTTPS");

  return {
    id: input.intent.assetId,
    workspaceId: input.intent.workspaceId,
    ...(input.intent.projectId ? { projectId: input.intent.projectId } : {}),
    blobKey: input.blob.pathname,
    blobUrl: input.blob.url,
    role: input.intent.role,
    mimeType: contentType,
    bytes: input.bytes,
  };
}
