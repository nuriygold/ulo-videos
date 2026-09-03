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

test("character uploads accept only format-matched Blender, glTF, GLB, and FBX MIME types", () => {
  const characterIntent = { ...intent, role: "character" as const, filename: "Lizard.BLEND" };
  const key = buildAssetBlobKey(characterIntent);

  assert.deepEqual(uploadPolicyForRole("character").allowedContentTypes, [
    "application/x-blender", "model/gltf+json", "model/gltf-binary", "application/octet-stream",
  ]);
  assert.deepEqual(parseAssetUploadIntent(JSON.stringify(characterIntent)), characterIntent);
  for (const format of [
    { filename: "hero.gltf", contentType: "model/gltf+json" },
    { filename: "hero.glb", contentType: "model/gltf-binary" },
    { filename: "hero.fbx", contentType: "application/octet-stream" },
  ]) {
    const formatIntent = { ...characterIntent, filename: format.filename };
    const formatKey = buildAssetBlobKey(formatIntent);
    assert.deepEqual(parseAssetUploadIntent(JSON.stringify(formatIntent)), formatIntent);
    assert.equal(assetRecordFromUpload({
      intent: formatIntent,
      blob: { pathname: formatKey, url: `https://blob.example/${formatKey}`, contentType: format.contentType },
      bytes: 42,
    }).mimeType, format.contentType);
  }
  assert.throws(
    () => parseAssetUploadIntent(JSON.stringify({ ...characterIntent, filename: "lizard.obj" })),
    /\.blend.*\.gltf.*\.glb.*\.fbx/i,
  );
  assert.throws(
    () => assetRecordFromUpload({
      intent: { ...characterIntent, filename: "hero.glb" },
      blob: { pathname: buildAssetBlobKey({ ...characterIntent, filename: "hero.glb" }), url: "https://blob.example/hero.glb", contentType: "model/gltf+json" },
      bytes: 42,
    }),
    /character .* uploads/i,
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

const completedAsset = {
  id: "a_789",
  workspaceId: "w_123",
  projectId: "p_456",
  blobKey: buildAssetBlobKey(intent),
  blobUrl: "https://blob.example/a_789",
  role: "source_video" as const,
  mimeType: "video/mp4",
  bytes: 42,
  sha256: "abc123",
};

const persistedCompletedAsset = {
  id: completedAsset.id,
  workspace_id: completedAsset.workspaceId,
  project_id: completedAsset.projectId,
  blob_key: completedAsset.blobKey,
  blob_url: completedAsset.blobUrl,
  role: completedAsset.role as string,
  mime_type: completedAsset.mimeType,
  bytes: completedAsset.bytes,
  sha256: completedAsset.sha256,
};

function duplicateAssetClient(existingAsset: typeof persistedCompletedAsset) {
  return {
    from: () => ({
      insert: async () => ({ error: { code: "23505", message: "duplicate key" } }),
      select: () => ({
        eq: () => ({
          maybeSingle: async () => ({ data: existingAsset, error: null }),
        }),
      }),
    }),
  } as never;
}

test("Supabase asset persistence treats an identical duplicate completion as a successful retry", async () => {
  const store = new SupabaseControlPlaneStore(duplicateAssetClient(persistedCompletedAsset));

  await assert.doesNotReject(store.saveAsset(completedAsset));
});

test("Supabase asset persistence rejects duplicate IDs with conflicting immutable metadata", async (t) => {
  const conflicts: Array<[string, Partial<typeof persistedCompletedAsset>]> = [
    ["workspace ownership", { workspace_id: "w_other" }],
    ["project ownership", { project_id: "p_other" }],
    ["blob key", { blob_key: "workspaces/w_123/projects/p_456/source_video/a_789/other.mp4" }],
    ["blob URL", { blob_url: "https://blob.example/other" }],
    ["role", { role: "logo" }],
    ["MIME type", { mime_type: "video/webm" }],
    ["size", { bytes: 43 }],
    ["checksum", { sha256: "different" }],
  ];

  for (const [name, conflict] of conflicts) {
    await t.test(name, async () => {
      const store = new SupabaseControlPlaneStore(duplicateAssetClient({
        ...persistedCompletedAsset,
        ...conflict,
      }));

      await assert.rejects(store.saveAsset(completedAsset), /conflicts with existing metadata/i);
    });
  }
});
