export type SetupStatus = {
  ready: boolean;
  services: { blob: boolean; supabase: boolean; queue: boolean; worker: boolean };
};

export function setupStatus(env: Record<string, string | undefined>): SetupStatus {
  const services = {
    blob: Boolean(env.BLOB_READ_WRITE_TOKEN),
    supabase: Boolean(env.SUPABASE_URL && env.SUPABASE_SERVICE_ROLE_KEY),
    queue: Boolean(env.RENDER_QUEUE_URL),
    worker: Boolean(env.RENDER_WORKER_SECRET),
  };
  return { ready: Object.values(services).every(Boolean), services };
}
