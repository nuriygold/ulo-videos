import { head } from "@vercel/blob";
import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  assetRecordFromUpload,
  buildAssetBlobKey,
  parseAssetUploadIntent,
  uploadPolicyForRole,
} from "../../../../src/web/asset-upload";
import { WORKSPACE_COOKIE } from "../../../../src/web/anonymous-workspace";
import { getSupabaseStore } from "../../../../src/web/supabase-store";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null) as HandleUploadBody | null;
  if (!body) return NextResponse.json({ error: "a Vercel Blob upload event is required" }, { status: 400 });

  const token = process.env.BLOB_READ_WRITE_TOKEN;
  if (!token) return NextResponse.json({ error: "Vercel Blob is not configured" }, { status: 503 });

  try {
    const cookieStore = await cookies();
    const requestWorkspaceId = cookieStore.get(WORKSPACE_COOKIE)?.value;
    const store = getSupabaseStore();
    const result = await handleUpload({
      request,
      body,
      token,
      onBeforeGenerateToken: async (pathname, clientPayload) => {
        if (!requestWorkspaceId) {
          throw new Error("an anonymous workspace must be established before uploading assets");
        }
        const intent = parseAssetUploadIntent(clientPayload);
        if (intent.workspaceId !== requestWorkspaceId) {
          throw new Error("the upload workspace does not match this browser workspace");
        }
        if (intent.projectId && !await store.projectBelongsToWorkspace(intent.projectId, requestWorkspaceId)) {
          throw new Error("the upload project does not belong to this browser workspace");
        }
        if (pathname !== buildAssetBlobKey(intent)) {
          throw new Error("the requested pathname does not match the scoped asset key");
        }
        const policy = uploadPolicyForRole(intent.role);
        return {
          allowedContentTypes: [...policy.allowedContentTypes],
          maximumSizeInBytes: policy.maximumSizeInBytes,
          addRandomSuffix: false,
          allowOverwrite: false,
          tokenPayload: JSON.stringify(intent),
        };
      },
      onUploadCompleted: async ({ blob, tokenPayload }) => {
        const intent = parseAssetUploadIntent(tokenPayload ?? null);
        const metadata = await head(blob.url, { token });
        const asset = assetRecordFromUpload({
          intent,
          blob: {
            pathname: metadata.pathname,
            url: blob.url,
            contentType: metadata.contentType,
          },
          bytes: metadata.size,
        });
        await store.saveAsset(asset);
      },
    });
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "asset upload could not be authorized" },
      { status: 400 },
    );
  }
}
