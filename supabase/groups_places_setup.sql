-- ============================================================
-- Comidinhas BFF - Setup de grupos/casais e lugares
-- Rode este script no SQL Editor do Supabase apos o profile_setup.sql.
-- ============================================================

-- 1. Adiciona active_group_id em profiles (sem foreign key ainda)
alter table public.profiles
  add column if not exists active_group_id uuid;


-- 2. Tabela de grupos / casais
create table if not exists public.groups (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  type text not null default 'couple',
  description text,
  owner_id uuid not null references public.profiles (id) on delete cascade,
  created_by uuid not null references public.profiles (id) on delete cascade,
  updated_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint groups_name_length check (char_length(name) between 1 and 80),
  constraint groups_type_valid check (type in ('couple', 'group'))
);

create index if not exists groups_owner_idx on public.groups (owner_id);


-- 3. Tabela de membros do grupo (relacionamento N:N)
create table if not exists public.group_members (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.groups (id) on delete cascade,
  profile_id uuid not null references public.profiles (id) on delete cascade,
  role text not null default 'member',
  invited_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  constraint group_members_role_valid check (role in ('owner', 'member')),
  constraint group_members_unique unique (group_id, profile_id)
);

create index if not exists group_members_profile_idx on public.group_members (profile_id);
create index if not exists group_members_group_idx on public.group_members (group_id);


-- 4. Liga active_group_id ao groups (depois que a tabela existe)
alter table public.profiles
  drop constraint if exists profiles_active_group_id_fkey;

alter table public.profiles
  add constraint profiles_active_group_id_fkey
    foreign key (active_group_id)
    references public.groups (id)
    on delete set null;


-- 5. Tabela de lugares / restaurantes
create table if not exists public.places (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.groups (id) on delete cascade,
  name text not null,
  category text,
  neighborhood text,
  city text,
  price_range smallint,
  link text,
  image_url text,
  notes text,
  status text not null default 'quero_ir',
  is_favorite boolean not null default false,
  created_by uuid not null references public.profiles (id) on delete cascade,
  updated_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint places_name_length check (char_length(name) between 1 and 120),
  constraint places_status_valid check (status in ('quero_ir', 'fomos', 'quero_voltar', 'nao_curti')),
  constraint places_price_range_valid check (price_range is null or price_range between 1 and 4),
  constraint places_link_length check (link is null or char_length(link) <= 500),
  constraint places_image_url_length check (image_url is null or char_length(image_url) <= 500),
  constraint places_notes_length check (notes is null or char_length(notes) <= 1000),
  constraint places_neighborhood_length check (neighborhood is null or char_length(neighborhood) <= 80),
  constraint places_city_length check (city is null or char_length(city) <= 80),
  constraint places_category_length check (category is null or char_length(category) <= 80)
);

create index if not exists places_group_idx on public.places (group_id);
create index if not exists places_group_status_idx on public.places (group_id, status);
create index if not exists places_group_favorite_idx on public.places (group_id, is_favorite) where is_favorite;
create index if not exists places_group_category_idx on public.places (group_id, category);
create index if not exists places_group_neighborhood_idx on public.places (group_id, neighborhood);
create index if not exists places_group_created_idx on public.places (group_id, created_at desc);


-- 6. Triggers de auditoria (updated_at, updated_by, created_by)
create or replace function public.set_audit_on_update()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  if auth.uid() is not null then
    new.updated_by = auth.uid();
  end if;
  return new;
end;
$$;

create or replace function public.set_audit_on_insert()
returns trigger
language plpgsql
as $$
begin
  if new.created_by is null and auth.uid() is not null then
    new.created_by = auth.uid();
  end if;
  return new;
end;
$$;

drop trigger if exists set_groups_audit_update on public.groups;
create trigger set_groups_audit_update
before update on public.groups
for each row execute function public.set_audit_on_update();

drop trigger if exists set_groups_audit_insert on public.groups;
create trigger set_groups_audit_insert
before insert on public.groups
for each row execute function public.set_audit_on_insert();

drop trigger if exists set_places_audit_update on public.places;
create trigger set_places_audit_update
before update on public.places
for each row execute function public.set_audit_on_update();

drop trigger if exists set_places_audit_insert on public.places;
create trigger set_places_audit_insert
before insert on public.places
for each row execute function public.set_audit_on_insert();


-- 7. Quando um grupo e criado, vincula o owner como membro automaticamente
create or replace function public.add_group_owner_membership()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.group_members (group_id, profile_id, role, invited_by)
  values (new.id, new.owner_id, 'owner', new.owner_id)
  on conflict (group_id, profile_id) do nothing;

  update public.profiles
  set active_group_id = new.id
  where id = new.owner_id and active_group_id is null;

  return new;
end;
$$;

drop trigger if exists after_groups_insert_owner on public.groups;
create trigger after_groups_insert_owner
after insert on public.groups
for each row execute function public.add_group_owner_membership();


-- 8. Helpers para RLS
create or replace function public.is_group_member(target_group_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.group_members gm
    where gm.group_id = target_group_id
      and gm.profile_id = auth.uid()
  );
$$;

create or replace function public.is_group_owner(target_group_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.group_members gm
    where gm.group_id = target_group_id
      and gm.profile_id = auth.uid()
      and gm.role = 'owner'
  );
$$;


-- 9. RLS - groups
alter table public.groups enable row level security;

drop policy if exists "groups_select_member" on public.groups;
create policy "groups_select_member"
on public.groups
for select
to authenticated
using (public.is_group_member(id));

drop policy if exists "groups_insert_self" on public.groups;
create policy "groups_insert_self"
on public.groups
for insert
to authenticated
with check (
  owner_id = (select auth.uid())
  and created_by = (select auth.uid())
);

drop policy if exists "groups_update_owner" on public.groups;
create policy "groups_update_owner"
on public.groups
for update
to authenticated
using (public.is_group_owner(id))
with check (public.is_group_owner(id));

drop policy if exists "groups_delete_owner" on public.groups;
create policy "groups_delete_owner"
on public.groups
for delete
to authenticated
using (public.is_group_owner(id));


-- 10. RLS - group_members
alter table public.group_members enable row level security;

drop policy if exists "group_members_select_member" on public.group_members;
create policy "group_members_select_member"
on public.group_members
for select
to authenticated
using (public.is_group_member(group_id));

drop policy if exists "group_members_insert_owner" on public.group_members;
create policy "group_members_insert_owner"
on public.group_members
for insert
to authenticated
with check (public.is_group_owner(group_id));

drop policy if exists "group_members_delete_owner_or_self" on public.group_members;
create policy "group_members_delete_owner_or_self"
on public.group_members
for delete
to authenticated
using (
  public.is_group_owner(group_id)
  or profile_id = (select auth.uid())
);


-- 11. RLS - places
alter table public.places enable row level security;

drop policy if exists "places_select_member" on public.places;
create policy "places_select_member"
on public.places
for select
to authenticated
using (public.is_group_member(group_id));

drop policy if exists "places_insert_member" on public.places;
create policy "places_insert_member"
on public.places
for insert
to authenticated
with check (
  public.is_group_member(group_id)
  and created_by = (select auth.uid())
);

drop policy if exists "places_update_member" on public.places;
create policy "places_update_member"
on public.places
for update
to authenticated
using (public.is_group_member(group_id))
with check (public.is_group_member(group_id));

drop policy if exists "places_delete_member" on public.places;
create policy "places_delete_member"
on public.places
for delete
to authenticated
using (public.is_group_member(group_id));


-- 12. RPC para o agregador da home
create or replace function public.home_summary(
  target_group_id uuid,
  top_limit integer default 5
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  result jsonb;
  group_payload jsonb;
  counters_payload jsonb;
  favorites_payload jsonb;
  latest_payload jsonb;
  want_to_go_payload jsonb;
  want_to_return_payload jsonb;
begin
  if not public.is_group_member(target_group_id) then
    raise exception 'forbidden: voce nao faz parte deste grupo';
  end if;

  select jsonb_build_object(
    'id', g.id,
    'name', g.name,
    'type', g.type,
    'description', g.description,
    'owner_id', g.owner_id,
    'created_at', g.created_at,
    'members', coalesce(
      (
        select jsonb_agg(
          jsonb_build_object(
            'profile_id', gm.profile_id,
            'role', gm.role,
            'full_name', p.full_name,
            'username', p.username,
            'avatar_url', p.avatar_url
          )
          order by gm.role desc, gm.created_at asc
        )
        from public.group_members gm
        join public.profiles p on p.id = gm.profile_id
        where gm.group_id = g.id
      ),
      '[]'::jsonb
    )
  )
  into group_payload
  from public.groups g
  where g.id = target_group_id;

  select jsonb_build_object(
    'total_places', count(*),
    'total_visited', count(*) filter (where status in ('fomos', 'quero_voltar')),
    'total_favorites', count(*) filter (where is_favorite),
    'total_want_to_go', count(*) filter (where status = 'quero_ir')
  )
  into counters_payload
  from public.places
  where group_id = target_group_id;

  select coalesce(
    jsonb_agg(to_jsonb(p) order by p.updated_at desc),
    '[]'::jsonb
  )
  into favorites_payload
  from (
    select *
    from public.places
    where group_id = target_group_id
      and is_favorite = true
    order by updated_at desc
    limit top_limit
  ) p;

  select coalesce(
    jsonb_agg(to_jsonb(p) order by p.created_at desc),
    '[]'::jsonb
  )
  into latest_payload
  from (
    select *
    from public.places
    where group_id = target_group_id
    order by created_at desc
    limit top_limit
  ) p;

  select coalesce(
    jsonb_agg(to_jsonb(p) order by p.created_at desc),
    '[]'::jsonb
  )
  into want_to_go_payload
  from (
    select *
    from public.places
    where group_id = target_group_id
      and status = 'quero_ir'
    order by created_at desc
    limit top_limit
  ) p;

  select coalesce(
    jsonb_agg(to_jsonb(p) order by p.updated_at desc),
    '[]'::jsonb
  )
  into want_to_return_payload
  from (
    select *
    from public.places
    where group_id = target_group_id
      and status = 'quero_voltar'
    order by updated_at desc
    limit top_limit
  ) p;

  result := jsonb_build_object(
    'group', group_payload,
    'counters', counters_payload,
    'top_favorites', favorites_payload,
    'latest_places', latest_payload,
    'want_to_go', want_to_go_payload,
    'want_to_return', want_to_return_payload
  );

  return result;
end;
$$;

revoke all on function public.home_summary(uuid, integer) from public;
grant execute on function public.home_summary(uuid, integer) to authenticated;


-- 13. RPC: define o grupo ativo do usuario
create or replace function public.set_active_group(target_group_id uuid)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if target_group_id is not null and not public.is_group_member(target_group_id) then
    raise exception 'forbidden: voce nao faz parte deste grupo';
  end if;

  update public.profiles
  set active_group_id = target_group_id
  where id = auth.uid();
end;
$$;

revoke all on function public.set_active_group(uuid) from public;
grant execute on function public.set_active_group(uuid) to authenticated;


-- 14. RPC: cria/garante o casal Filipe e Victor a partir de dois emails
create or replace function public.seed_couple_group(
  group_name text,
  owner_email text,
  partner_email text,
  group_type text default 'couple',
  group_description text default null
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  owner_profile_id uuid;
  partner_profile_id uuid;
  new_group_id uuid;
begin
  if owner_email is null or partner_email is null then
    raise exception 'owner_email e partner_email sao obrigatorios';
  end if;

  select id
  into owner_profile_id
  from public.profiles
  where lower(email) = lower(owner_email)
  limit 1;

  if owner_profile_id is null then
    raise exception 'Perfil com email % nao encontrado em public.profiles', owner_email;
  end if;

  select id
  into partner_profile_id
  from public.profiles
  where lower(email) = lower(partner_email)
  limit 1;

  if partner_profile_id is null then
    raise exception 'Perfil com email % nao encontrado em public.profiles', partner_email;
  end if;

  select g.id
  into new_group_id
  from public.groups g
  where g.name = group_name
    and g.owner_id = owner_profile_id
  limit 1;

  if new_group_id is null then
    insert into public.groups (name, type, description, owner_id, created_by)
    values (
      group_name,
      coalesce(group_type, 'couple'),
      group_description,
      owner_profile_id,
      owner_profile_id
    )
    returning id into new_group_id;
  end if;

  insert into public.group_members (group_id, profile_id, role, invited_by)
  values (new_group_id, owner_profile_id, 'owner', owner_profile_id)
  on conflict (group_id, profile_id) do nothing;

  insert into public.group_members (group_id, profile_id, role, invited_by)
  values (new_group_id, partner_profile_id, 'member', owner_profile_id)
  on conflict (group_id, profile_id) do nothing;

  update public.profiles
  set active_group_id = new_group_id
  where id in (owner_profile_id, partner_profile_id)
    and active_group_id is null;

  return new_group_id;
end;
$$;

revoke all on function public.seed_couple_group(text, text, text, text, text) from public;
grant execute on function public.seed_couple_group(text, text, text, text, text) to authenticated;


-- 15. Wrapper especifico para Filipe e Victor.
--     Os usuarios precisam existir antes em auth.users / public.profiles.
create or replace function public.seed_filipe_victor(
  filipe_email text default 'filipe@comidinhas.app',
  victor_email text default 'victor@comidinhas.app'
)
returns uuid
language sql
security definer
set search_path = ''
as $$
  select public.seed_couple_group(
    'Filipe e Victor',
    filipe_email,
    victor_email,
    'couple',
    'Casal inicial Filipe e Victor'
  );
$$;

revoke all on function public.seed_filipe_victor(text, text) from public;
grant execute on function public.seed_filipe_victor(text, text) to authenticated;
