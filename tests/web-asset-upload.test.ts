import test from "node:test";
import assert from "node:assert/strict";
import {
  assetRecordFromUpload,
  buildAssetBlobKey,
  parseAssetUploadIntent,
  uploadPolicyForRole,
} from "../src/web/asset-upload";

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
