-- Run once in Supabase: SQL Editor -> New query -> paste -> Run.
-- Visit log for the site owner's statistics: one row per user per day (Israel time), with the first and last visit.

create table if not exists public.visits (
  user_id  uuid not null references auth.users (id) on delete cascade,
  day      date not null,
  first_at timestamptz not null default now(),
  last_at  timestamptz not null default now(),
  primary key (user_id, day)
);

-- Row level security: a user can only add or touch their own day; nobody can read the table directly
alter table public.visits enable row level security;

drop policy if exists "insert own visit" on public.visits;
create policy "insert own visit" on public.visits
  for insert to authenticated with check (auth.uid() = user_id);

drop policy if exists "update own visit" on public.visits;
create policy "update own visit" on public.visits
  for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- The statistics, for the site owner only (any other account gets no rows)
create or replace function public.admin_stats()
returns table (
  user_id uuid, username text, email text, registered timestamptz, last_sign_in timestamptz,
  last_visit timestamptz, days_7 int, days_30 int, days_total int
)
language sql security definer set search_path = public as $$
  select u.id, u.raw_user_meta_data ->> 'username', u.email, u.created_at, u.last_sign_in_at,
         max(v.last_at),
         (count(v.day) filter (where v.day > (now() at time zone 'Asia/Jerusalem')::date - 7))::int,
         (count(v.day) filter (where v.day > (now() at time zone 'Asia/Jerusalem')::date - 30))::int,
         count(v.day)::int
  from auth.users u
  left join public.visits v on v.user_id = u.id
  where lower(auth.jwt() ->> 'email') = 'roigreen111@gmail.com'
  group by u.id
  order by max(v.last_at) desc nulls last, u.created_at desc;
$$;

revoke all on function public.admin_stats() from public, anon;
grant execute on function public.admin_stats() to authenticated;
