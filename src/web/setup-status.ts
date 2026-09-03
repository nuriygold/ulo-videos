export type RendererMode = "vercel_fallback" | "external_worker";

export type RendererCapabilities = {
  freezeResume: boolean; logo: boolean; captions: boolean; character: boolean;
  sourceAudio: boolean; speech: boolean; lipSync: boolean; characterFormats: string[];
};

export type RendererHealth = { mode: RendererMode; reachable: boolean; characterFormats?: string[] };

export type SetupStatus = {
  ready: boolean;
  services: { blob: boolean; supabase: boolean; queue: boolean; worker: boolean };
  renderer: RendererHealth & { capabilities: RendererCapabilities };
};

const FALLBACK_CAPABILITIES: RendererCapabilities = { freezeResume: true, logo: true, captions: true, character: false, sourceAudio: false, speech: false, lipSync: false, characterFormats: [] };
const EXTERNAL_CHARACTER_FORMATS = [".blend", ".gltf", ".glb", ".fbx"];

function externalCapabilities(reportedFormats: string[] | undefined): RendererCapabilities {
  const characterFormats = [
    ".blend",
    ...EXTERNAL_CHARACTER_FORMATS.slice(1).filter((format) => reportedFormats?.includes(format)),
  ];
  return { freezeResume: true, logo: true, captions: true, character: true, sourceAudio: false, speech: false, lipSync: false, characterFormats };
}

export function fallbackRendererHealth(reachable = false): RendererHealth {
  return { mode: "vercel_fallback", reachable };
}

export async function rendererHealthForQueue(queueUrl: string | undefined, request: typeof fetch = fetch): Promise<RendererHealth> {
  if (!queueUrl) return fallbackRendererHealth();
  try {
    const response = await request(queueUrl, { method: "GET", cache: "no-store", signal: AbortSignal.timeout(5_000) });
    const health = await response.json() as { ok?: unknown; mode?: unknown; capabilities?: { characterFormats?: unknown } };
    if (response.ok && health.ok === true && health.mode === "external_worker") {
      const characterFormats = Array.isArray(health.capabilities?.characterFormats)
        ? health.capabilities.characterFormats.filter((format): format is string => typeof format === "string")
        : undefined;
      return { mode: "external_worker", reachable: true, characterFormats };
    }
    if (response.ok && health.ok === true && health.mode === "vercel_fallback") return fallbackRendererHealth(true);
  } catch { /* Setup status stays useful even when a live readiness probe fails. */ }
  return fallbackRendererHealth();
}

export function setupStatus(env: Record<string, string | undefined>, health: RendererHealth = fallbackRendererHealth(Boolean(env.RENDER_QUEUE_URL))): SetupStatus {
  const services = {
    blob: Boolean(env.BLOB_READ_WRITE_TOKEN),
    supabase: Boolean(env.SUPABASE_URL && env.SUPABASE_SERVICE_ROLE_KEY),
    queue: Boolean(env.RENDER_QUEUE_URL),
    worker: Boolean(env.RENDER_WORKER_SECRET),
  };
  const capabilities = health.mode === "external_worker" ? externalCapabilities(health.characterFormats) : FALLBACK_CAPABILITIES;
  return { ready: Object.values(services).every(Boolean) && health.reachable, services, renderer: { ...health, capabilities } };
}
