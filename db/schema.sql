-- Hosted control-plane schema. Scene data is JSONB; media bytes live in Blob.
create table if not exists workspaces (
  id text primary key,
  created_at timestamptz not null default now()
);

create table if not exists projects (
  id text primary key,
  workspace_id text not null references workspaces(id),
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists assets (
  id text primary key,
  workspace_id text not null references workspaces(id),
  project_id text references projects(id),
  blob_key text not null,
  blob_url text not null,
  role text not null,
  mime_type text not null,
  bytes bigint not null,
  sha256 text,
  created_at timestamptz not null default now()
);

create table if not exists shots (
  id text primary key,
  project_id text not null references projects(id),
  name text not null,
  template text not null,
  template_version integer not null,
  spec jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists render_jobs (
  id text primary key,
  workspace_id text not null references workspaces(id),
  project_id text not null references projects(id),
  shot_id text not null references shots(id),
  template text not null,
  template_version integer not null,
  spec_snapshot jsonb not null,
  status text not null check (status in ('queued','preparing','downloading_assets','generating_audio','lip_sync','building_scene','rendering','encoding','uploading','completed','failed')),
  progress integer not null default 0 check (progress between 0 and 100),
  attempt integer not null default 1,
  worker_id text,
  output_asset_id text references assets(id),
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);

create index if not exists projects_workspace_idx on projects(workspace_id);
create index if not exists assets_workspace_idx on assets(workspace_id);
create index if not exists shots_project_idx on shots(project_id);
create index if not exists render_jobs_workspace_status_idx on render_jobs(workspace_id, status);
