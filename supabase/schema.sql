-- Schema for the sixwordidea.com backend.
-- Run this once in the Supabase SQL editor (or via `supabase db push`).

create table public.ideas (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  title text not null,
  story text not null,
  doc jsonb not null,
  published_by uuid not null default auth.uid() references auth.users (id),
  published_at timestamptz not null default now()
);

alter table public.ideas enable row level security;

-- Anyone may read published ideas (the site and agents fetch anonymously).
create policy "public read"
  on public.ideas for select
  using (true);

-- Publishing requires a signed-in user, and the row records who published.
create policy "authenticated insert"
  on public.ideas for insert
  to authenticated
  with check (published_by = auth.uid());
