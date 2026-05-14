-- =============================================================================
-- NautiCAI — Supabase / Postgres schema
-- =============================================================================
-- HOW TO USE
-- 1. Open your Supabase project → SQL Editor → New Query.
-- 2. Paste the contents of this file and run it.
-- 3. Settings → Database → Connection String → copy "Connection pooling" URI
--    (port 6543 with `?pgbouncer=true&sslmode=require`) for serverless workloads
--    OR the direct Connection string (port 5432) for the FastAPI backend.
-- 4. In `backend/.env` set:
--        DATABASE_URL=postgresql://postgres:<password>@<host>:5432/postgres
--        JWT_SECRET=<random-long-string>
-- 5. Restart the backend. It will run `CREATE TABLE IF NOT EXISTS …` via
--    SQLAlchemy and use the tables created below.
--
-- NOTE: NautiCAI manages auth itself (bcrypt + JWT). We do NOT depend on the
--       Supabase Auth `auth.users` table. You only need Postgres from Supabase.
-- =============================================================================

-- pgcrypto provides gen_random_uuid() — handy if you want to generate UUIDs in DB.
create extension if not exists pgcrypto;

-- -----------------------------------------------------------------------------
-- COMPANIES  (one row per tenant)
-- -----------------------------------------------------------------------------
create table if not exists public.companies (
    id              text primary key default replace(gen_random_uuid()::text, '-', ''),
    name            text not null,
    tagline         text default 'Marine inspection & cleaning services',
    address         text default '',
    phone           text default '',
    email           text default '',
    website         text default '',
    logo_path       text default '',
    report_footer   text default 'Powered by NautiCAI',
    -- Extended company profile (shows on the report cover)
    country               text default '',
    registration_number   text default '',
    tax_number            text default '',
    class_approvals       jsonb default '[]'::jsonb,
    diving_certifications text default '',
    insurance             text default '',
    report_prefix         text default 'NAUTICAI-REP',
    established_year      text default '',
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

-- If you ran an earlier version of this script, run these to upgrade in place:
alter table public.companies add column if not exists country               text default '';
alter table public.companies add column if not exists registration_number   text default '';
alter table public.companies add column if not exists tax_number            text default '';
alter table public.companies add column if not exists class_approvals       jsonb default '[]'::jsonb;
alter table public.companies add column if not exists diving_certifications text default '';
alter table public.companies add column if not exists insurance             text default '';
alter table public.companies add column if not exists report_prefix         text default 'NAUTICAI-REP';
alter table public.companies add column if not exists established_year      text default '';

create index if not exists companies_email_idx on public.companies (lower(email));

-- -----------------------------------------------------------------------------
-- USERS  (login credentials, scoped to a company)
-- -----------------------------------------------------------------------------
create table if not exists public.users (
    id              text primary key default replace(gen_random_uuid()::text, '-', ''),
    company_id      text not null references public.companies(id) on delete cascade,
    email           text not null,
    password_hash   text not null,
    full_name       text default '',
    role            text default 'owner',          -- owner | supervisor | viewer
    is_active       boolean default true,
    created_at      timestamptz default now(),
    last_login_at   timestamptz
);

create unique index if not exists users_email_unique on public.users (lower(email));
create index        if not exists users_company_idx on public.users (company_id);

-- -----------------------------------------------------------------------------
-- REPORTS  (one row per marine inspection report)
-- -----------------------------------------------------------------------------
create table if not exists public.reports (
    id                  text primary key,
    company_id          text references public.companies(id) on delete cascade,
    vessel_name         text default '',
    vessel_type         text default '',
    vessel_class        text default '',
    job_no              text default '',
    job_scope           text default '',
    loa                 text default '',
    draft               text default '',
    location            text default '',
    dive_date           text default '',
    weather             text default '',
    sea                 text default '',
    visibility          text default '',
    tide                text default '',
    captain             text default '',
    dive_supervisor     text default '',
    divers              text default '',
    boat_captain        text default '',
    status              text default 'draft',          -- draft | in_review | completed
    severity            text default 'A',              -- A | B | C | D
    avg_fouling         double precision default 0.0,
    notes               text default '',
    extra               jsonb default '{}'::jsonb,
    pdf_path            text default '',
    region_inspections  jsonb default '{}'::jsonb,
    vessel_image_id     text default '',
    created_at          timestamptz default now(),
    updated_at          timestamptz default now()
);

create index if not exists reports_company_created_idx on public.reports (company_id, created_at desc);
create index if not exists reports_company_status_idx  on public.reports (company_id, status);

-- -----------------------------------------------------------------------------
-- IMAGES  (one row per uploaded photo, including OCR cover photos)
-- -----------------------------------------------------------------------------
create table if not exists public.images (
    id              text primary key,
    company_id      text references public.companies(id) on delete cascade,
    report_id       text references public.reports(id),
    filename        text not null,
    path            text not null,
    width           integer default 0,
    height          integer default 0,
    region          text default '',           -- Bow | Propeller | … | vessel_cover
    region_conf     double precision default 0.0,
    stage           text default '',           -- before | after
    stage_conf      double precision default 0.0,
    species_top     text default '',           -- algae | barnacles | clean_paint | macroalgae | mussels
    species_dist    jsonb default '{}'::jsonb,
    fouling_pct     double precision default 0.0,
    severity        text default 'A',
    ocr_text        jsonb default '[]'::jsonb,
    vessel_guess    text default '',
    created_at      timestamptz default now()
);

create index if not exists images_company_idx     on public.images (company_id);
create index if not exists images_report_idx      on public.images (report_id);
create index if not exists images_company_region  on public.images (company_id, region);

-- -----------------------------------------------------------------------------
-- 5. Clients (vessel-owner directory — entered once, reused on every report)
-- -----------------------------------------------------------------------------
create table if not exists public.clients (
    id              text primary key,
    company_id      text not null references public.companies(id) on delete cascade,
    name            text not null,                  -- vessel-owner / client company
    address         text default '',
    contact_person  text default '',
    contact_email   text default '',
    contact_phone   text default '',
    country         text default '',
    notes           text default '',
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);
create index if not exists clients_company_idx      on public.clients (company_id);
create index if not exists clients_company_name_idx on public.clients (company_id, name);

-- Allow `reports` to reference a saved client by id (nullable, kept on delete)
alter table public.reports
    add column if not exists client_id text references public.clients(id) on delete set null;
create index if not exists reports_client_idx on public.reports (client_id);

-- -----------------------------------------------------------------------------
-- (Optional) Row-Level Security
-- -----------------------------------------------------------------------------
-- The backend connects with the SERVICE ROLE so RLS isn't strictly required.
-- If you ever expose these tables directly to PostgREST/anon role, you should
-- enable RLS and add per-tenant policies. Uncomment the block below to enable.
--
-- alter table public.companies enable row level security;
-- alter table public.users     enable row level security;
-- alter table public.reports   enable row level security;
-- alter table public.images    enable row level security;
--
-- -- Allow the service role full access (this is the role our FastAPI backend uses):
-- create policy "service_role_all_companies" on public.companies for all to service_role using (true) with check (true);
-- create policy "service_role_all_users"     on public.users     for all to service_role using (true) with check (true);
-- create policy "service_role_all_reports"   on public.reports   for all to service_role using (true) with check (true);
-- create policy "service_role_all_images"    on public.images    for all to service_role using (true) with check (true);

-- -----------------------------------------------------------------------------
-- Done. Grant the connection a sane search_path.
-- -----------------------------------------------------------------------------
-- alter database postgres set search_path = public;

-- Quick sanity check (uncomment to run):
-- select 'companies' tbl, count(*) from public.companies
-- union all select 'users',   count(*) from public.users
-- union all select 'reports', count(*) from public.reports
-- union all select 'images',  count(*) from public.images;
