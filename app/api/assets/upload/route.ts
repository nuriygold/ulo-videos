import { head } from "@vercel/blob";
import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  assetRecordFromUpload,
  authorizeAssetUpload,
  parseAssetUploadIntent,
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
        const { intent, policy } = await authorizeAssetUpload({
          requestWorkspaceId,
          pathname,
          clientPayload,
          projectBelongsToWorkspace: (projectId, workspaceId) => store.projectBelongsToWorkspace(projectId, workspaceId),
        });
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
