alter table public.render_jobs add column if not exists worker_id text;
alter table public.render_jobs add column if not exists lease_expires_at timestamptz;
