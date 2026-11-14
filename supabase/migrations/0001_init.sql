-- Nexus Viewer — initial schema.
-- Run this once in the Supabase SQL editor (or `supabase db push`).
-- The backend writes with the SERVICE-ROLE key; browsers only ever get the ANON key.
-- Community tables (profiles, discoveries, saved_views) are NOT created yet: see
-- PROJECT_EXPLAINED.md, "Not implemented yet".

create extension if not exists pgcrypto;

-- 1. Data releases (drives "easy to update")
create table if not exists releases (
  id                 text primary key,          -- 'dr1', 'qr3'
  label              text not null,             -- 'Data Release 1'
  sia_collections    text[] not null,           -- {'spherex_dr1','spherex_dr1_deep'}
  tap_release_filter text,                      -- value of obs_collection in TAP
  s3_prefix          text,                      -- 'dr1/' in s3://nasa-irsa-spherex
  sapm_path_template text,                      -- solid-angle pixel map path, {k} = detector
  doi                text,
  priority           int not null default 0,    -- higher wins when an exposure is in several releases
  is_active          boolean not null default true,
  released_at        date,
  last_synced_at     timestamptz,
  notes              text
);

-- 2. Featured / named targets
create table if not exists targets (
  id               uuid primary key default gen_random_uuid(),
  slug             text unique not null,        -- 'barnards-star'
  name             text not null,
  ra_deg           double precision not null,   -- catalogue position at ref_epoch
  dec_deg          double precision not null,
  ref_epoch        double precision default 2000.0,
  pmra_masyr       double precision,
  pmdec_masyr      double precision,
  parallax_mas     double precision,
  view_ra          double precision,            -- position propagated to J2026.0 (default view centre)
  view_dec         double precision,
  category         text,                        -- 'high-pm-star','brown-dwarf','variable', ...
  description      text,
  what_to_see      text,
  recommended_view jsonb,                       -- {band:'D6', fov:180, diff:'first', zoom:4}
  thumbnail_path   text,
  is_featured      boolean default true,
  sort_order       int default 0
);

-- 3. Cached exposure lists per position (cheap metadata)
create table if not exists observation_cache (
  key        text primary key,                  -- hash(ra, dec rounded, collections)
  ra_deg     double precision,
  dec_deg    double precision,
  releases   text[],
  payload    jsonb not null,                    -- {"exposures": [...]}
  created_at timestamptz default now()
);

-- 4. Frame sets (one per unique job request). Frame metadata is kept in payload.frames.
--    The `frames` table below is an optional per-frame mirror for SQL queries; the current
--    backend does not fill it yet (see "Not implemented yet").
create table if not exists frame_sets (
  request_hash     text primary key,
  request          jsonb not null,              -- normalized request
  release_versions jsonb not null,              -- {"dr1":"l2b-v27-2026-245", ...}
  status           text not null,               -- 'done' | 'partial' | 'failed'
  n_frames         int,
  wcs              jsonb,                       -- common grid (CRVAL, CDELT, NAXIS)
  payload          jsonb,                       -- full record served by GET /api/framesets/{hash}
  created_at       timestamptz default now(),
  last_accessed_at timestamptz default now()
);

create table if not exists frames (
  id           uuid primary key default gen_random_uuid(),
  request_hash text references frame_sets(request_hash) on delete cascade,
  idx          int not null,
  t_start      timestamptz, t_end timestamptz, t_mid timestamptz,
  band         text,
  lambda_um    double precision,
  n_exposures  int,
  obs_ids      text[],
  flag_summary jsonb,                           -- {"GHOST": 12, "PERSIST": 3, ...}
  stats        jsonb,                           -- [{p0_5, p99_5, median, mad}, ...] per channel
  data_path    text not null,                   -- storage: frames/{hash}/{idx}.bin
  flags_path   text,
  png_path     text,
  unique (request_hash, idx)
);

-- 5. Jobs (progress is broadcast with Realtime)
create table if not exists jobs (
  id           uuid primary key default gen_random_uuid(),
  request_hash text not null,
  status       text not null default 'queued',  -- queued|running|done|failed
  progress     real default 0,
  stage        text,
  error        text,
  created_at   timestamptz default now(),
  updated_at   timestamptz default now()
);
do $$ begin
  alter publication supabase_realtime add table jobs;
exception when others then null;  -- already added / publication missing locally
end $$;

-- 6. Spectra / light-curve cache
create table if not exists photometry_cache (
  key        text primary key,                  -- hash(ra, dec, aperture, releases, versions, pm)
  kind       text not null default 'points',
  payload    jsonb not null,
  created_at timestamptz default now()
);

-- 7. Name resolution & catalogue overlay cache
create table if not exists resolved_names (name_norm text primary key, payload jsonb, created_at timestamptz default now());
create table if not exists overlay_cache  (key text primary key, catalog text, payload jsonb, created_at timestamptz default now());

-- ---------------------------------------------------------------- Row Level Security
alter table releases          enable row level security;
alter table targets           enable row level security;
alter table frame_sets        enable row level security;
alter table frames            enable row level security;
alter table jobs              enable row level security;
alter table observation_cache enable row level security;
alter table photometry_cache  enable row level security;
alter table resolved_names    enable row level security;
alter table overlay_cache     enable row level security;

-- Public read where the browser may need it. The service-role key bypasses RLS, so the
-- backend can write everything; anon users can write nothing.
create policy "public read releases"   on releases   for select using (true);
create policy "public read targets"    on targets    for select using (true);
create policy "public read frame_sets" on frame_sets for select using (true);
create policy "public read frames"     on frames     for select using (true);
create policy "public read jobs"       on jobs       for select using (true);  -- needed for Realtime progress

-- ---------------------------------------------------------------- Storage
insert into storage.buckets (id, name, public) values ('frames', 'frames', true)  on conflict (id) do nothing;
insert into storage.buckets (id, name, public) values ('cutouts', 'cutouts', false) on conflict (id) do nothing;

-- ---------------------------------------------------------------- Cache eviction
-- Delete frame sets not used for N days (their storage objects should be removed by the
-- backend; see PROJECT_EXPLAINED.md). Schedule with pg_cron if available:
--   select cron.schedule('evict-frames', '0 3 * * *', $$select evict_stale_frame_sets(30)$$);
create or replace function evict_stale_frame_sets(days int default 30) returns int
language sql as $$
  with d as (delete from frame_sets where last_accessed_at < now() - make_interval(days => days) returning 1)
  select count(*)::int from d;
$$;
