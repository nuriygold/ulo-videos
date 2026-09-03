import test from "node:test";
import assert from "node:assert/strict";
import {
  assetRecordFromUpload,
  authorizeAssetUpload,
  buildAssetBlobKey,
  parseAssetUploadIntent,
  uploadPolicyForRole,
} from "../src/web/asset-upload";
import { SupabaseControlPlaneStore } from "../src/web/supabase-store";

const intent = {
  assetId: "a_789",
  workspaceId: "w_123",
  projectId: "p_456",
  role: "source_video" as const,
  filename: "House Leak.mp4",
};

test("buildAssetBlobKey creates a deterministic workspace/project/role scope", () => {
  assert.equal(
    buildAssetBlobKey(intent),
    "workspaces/w_123/projects/p_456/source_video/a_789/House-Leak.mp4",
  );
});

test("buildAssetBlobKey rejects path traversal and invalid scope identifiers", () => {
  assert.throws(() => buildAssetBlobKey({ ...intent, filename: "../leak.mp4" }), /filename/i);
  assert.throws(() => buildAssetBlobKey({ ...intent, workspaceId: "../other" }), /workspaceId/i);
});

test("parseAssetUploadIntent validates upload metadata and rejects render outputs", () => {
  assert.deepEqual(parseAssetUploadIntent(JSON.stringify(intent)), intent);
  assert.throws(
    () => parseAssetUploadIntent(JSON.stringify({ ...intent, role: "render_output" })),
    /worker-only/i,
  );
  assert.throws(() => parseAssetUploadIntent("{}"), /assetId/i);
});

test("upload policies restrict MIME types and provide finite size limits", () => {
  const sourcePolicy = uploadPolicyForRole("source_video");
  assert.ok(sourcePolicy.allowedContentTypes.includes("video/mp4"));
  assert.ok(sourcePolicy.maximumSizeInBytes > 0);
  assert.ok(Number.isSafeInteger(sourcePolicy.maximumSizeInBytes));
  assert.throws(() => uploadPolicyForRole("render_output"), /worker-only/i);
  assert.throws(() => uploadPolicyForRole("constructor" as never), /not allowed/i);
});

test("character uploads require a Blender filename and Blender MIME type", () => {
  const characterIntent = { ...intent, role: "character" as const, filename: "Lizard.BLEND" };
  const key = buildAssetBlobKey(characterIntent);

  assert.deepEqual(uploadPolicyForRole("character").allowedContentTypes, ["application/x-blender"]);
  assert.deepEqual(parseAssetUploadIntent(JSON.stringify(characterIntent)), characterIntent);
  assert.throws(
    () => parseAssetUploadIntent(JSON.stringify({ ...characterIntent, filename: "lizard.obj" })),
    /\.blend/i,
  );
  assert.throws(
    () => assetRecordFromUpload({
      intent: characterIntent,
      blob: { pathname: key, url: `https://blob.example/${key}`, contentType: "application/octet-stream" },
      bytes: 42,
    }),
    /content type/i,
  );
});

test("authorizeAssetUpload enforces workspace, project ownership, and exact scoped path", async () => {
  const payload = JSON.stringify(intent);
  const pathname = buildAssetBlobKey(intent);
  const belongs = async () => true;
  await assert.doesNotReject(authorizeAssetUpload({ requestWorkspaceId: "w_123", pathname, clientPayload: payload, projectBelongsToWorkspace: belongs }));
  await assert.rejects(authorizeAssetUpload({ requestWorkspaceId: undefined, pathname, clientPayload: payload, projectBelongsToWorkspace: belongs }), /workspace must be established/i);
  await assert.rejects(authorizeAssetUpload({ requestWorkspaceId: "w_other", pathname, clientPayload: payload, projectBelongsToWorkspace: belongs }), /workspace/i);
  await assert.rejects(authorizeAssetUpload({ requestWorkspaceId: "w_123", pathname, clientPayload: payload }), /ownership cannot be verified/i);
  await assert.rejects(authorizeAssetUpload({ requestWorkspaceId: "w_123", pathname, clientPayload: payload, projectBelongsToWorkspace: async () => false }), /project/i);
  await assert.rejects(authorizeAssetUpload({ requestWorkspaceId: "w_123", pathname: `${pathname}-other`, clientPayload: payload, projectBelongsToWorkspace: belongs }), /pathname/i);
});

test("assetRecordFromUpload accepts verified completion metadata", () => {
  const key = buildAssetBlobKey(intent);
  assert.deepEqual(
    assetRecordFromUpload({
      intent,
      blob: { pathname: key, url: `https://blob.example/${key}`, contentType: "video/mp4" },
      bytes: 42,
    }),
    {
      id: "a_789",
      workspaceId: "w_123",
      projectId: "p_456",
      blobKey: key,
      blobUrl: `https://blob.example/${key}`,
      role: "source_video",
      mimeType: "video/mp4",
      bytes: 42,
    },
  );
});

test("assetRecordFromUpload rejects mismatched paths, MIME types, and sizes", () => {
  const key = buildAssetBlobKey(intent);
  const base = {
    intent,
    blob: { pathname: key, url: `https://blob.example/${key}`, contentType: "video/mp4" },
    bytes: 42,
  };
  assert.throws(
    () => assetRecordFromUpload({ ...base, blob: { ...base.blob, pathname: "other.mp4" } }),
    /pathname/i,
  );
  assert.throws(
    () => assetRecordFromUpload({ ...base, blob: { ...base.blob, contentType: "text/plain" } }),
    /content type/i,
  );
  assert.throws(
    () => assetRecordFromUpload({ ...base, bytes: uploadPolicyForRole("source_video").maximumSizeInBytes + 1 }),
    /size/i,
  );
});

test("Supabase asset persistence rejects a duplicate ID without replacing its immutable claim", async () => {
  const originalAsset = {
    id: "a_789",
    workspace_id: "w_original",
    blob_key: "workspaces/w_original/workspace-assets/logo/a_789/original.png",
  };
  let storedAsset = { ...originalAsset };
  const fakeClient = {
    from: () => ({
      insert: async () => ({ error: { code: "23505", message: "duplicate key" } }),
      upsert: async (replacement: typeof storedAsset) => {
        storedAsset = replacement;
        return { error: null };
      },
    }),
  } as never;
  const store = new SupabaseControlPlaneStore(fakeClient);
  await assert.rejects(store.saveAsset({
    id: "a_789",
    workspaceId: "w_123",
    projectId: "p_456",
    blobKey: buildAssetBlobKey(intent),
    blobUrl: "https://blob.example/a_789",
    role: "source_video",
    mimeType: "video/mp4",
    bytes: 42,
  }), (error: unknown) => Boolean(error && typeof error === "object" && "code" in error && error.code === "23505"));
  assert.deepEqual(storedAsset, originalAsset);
});
