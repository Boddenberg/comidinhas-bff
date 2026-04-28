-- Idempotent production backfill for the Comidinhas BFF.
-- Safe to run on an existing Supabase project: only creates missing objects
-- and adds missing columns/indexes/policies.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Shared helpers
-- ---------------------------------------------------------------------------

create or replace function public.set_profile_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create or replace function public.atualizar_timestamp()
returns trigger
language plpgsql
as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

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
security definer
as $$
begin
  if new.created_by is null then
    new.created_by := auth.uid();
  end if;
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- Auth-backed legacy schema: profiles, groups, group_members, places, photos.
-- ---------------------------------------------------------------------------

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text,
  username text,
  full_name text,
  phone text,
  birth_date date,
  city text,
  state text,
  bio text,
  favorite_cuisine text,
  avatar_path text,
  avatar_url text,
  preferences jsonb not null default '{}'::jsonb,
  extra_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.profiles
  add column if not exists email text,
  add column if not exists username text,
  add column if not exists full_name text,
  add column if not exists phone text,
  add column if not exists birth_date date,
  add column if not exists city text,
  add column if not exists state text,
  add column if not exists bio text,
  add column if not exists favorite_cuisine text,
  add column if not exists avatar_path text,
  add column if not exists avatar_url text,
  add column if not exists preferences jsonb not null default '{}'::jsonb,
  add column if not exists extra_data jsonb not null default '{}'::jsonb,
  add column if not exists active_group_id uuid,
  add column if not exists created_at timestamptz not null default timezone('utc', now()),
  add column if not exists updated_at timestamptz not null default timezone('utc', now());

create unique index if not exists profiles_username_lower_idx
  on public.profiles (lower(username))
  where username is not null;

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
before update on public.profiles
for each row
execute function public.set_profile_updated_at();

create or replace function public.sync_profile_from_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (
    id,
    email,
    username,
    full_name
  )
  values (
    new.id,
    new.email,
    nullif(new.raw_user_meta_data ->> 'username', ''),
    nullif(new.raw_user_meta_data ->> 'full_name', '')
  )
  on conflict (id) do update
  set
    email = excluded.email,
    username = coalesce(excluded.username, public.profiles.username),
    full_name = coalesce(excluded.full_name, public.profiles.full_name),
    updated_at = timezone('utc', now());

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row
execute function public.sync_profile_from_auth_user();

drop trigger if exists on_auth_user_updated on auth.users;
create trigger on_auth_user_updated
after update of email, raw_user_meta_data on auth.users
for each row
execute function public.sync_profile_from_auth_user();

create table if not exists public.groups (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  type text not null default 'couple',
  description text,
  owner_id uuid not null references public.profiles (id) on delete cascade,
  created_by uuid references public.profiles (id) on delete cascade,
  updated_by uuid references public.profiles (id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  constraint groups_name_length check (char_length(name) between 1 and 80),
  constraint groups_type_valid check (type in ('couple', 'group'))
);

create index if not exists groups_owner_idx on public.groups (owner_id);

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

alter table public.profiles
  drop constraint if exists profiles_active_group_id_fkey;

alter table public.profiles
  add constraint profiles_active_group_id_fkey
  foreign key (active_group_id)
  references public.groups (id)
  on delete set null;

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
  created_by uuid references public.profiles (id) on delete cascade,
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

create table if not exists public.place_photos (
  id uuid primary key default gen_random_uuid(),
  place_id uuid not null references public.places (id) on delete cascade,
  group_id uuid not null references public.groups (id) on delete cascade,
  storage_path text not null,
  public_url text not null,
  is_cover boolean not null default false,
  sort_order smallint not null default 0,
  created_by uuid references public.profiles (id) on delete cascade,
  created_at timestamptz not null default timezone('utc', now()),
  constraint place_photos_sort_order_valid check (sort_order >= 0)
);

create index if not exists place_photos_place_idx on public.place_photos (place_id, sort_order);
create index if not exists place_photos_cover_idx on public.place_photos (place_id, is_cover) where is_cover;
create index if not exists place_photos_group_idx on public.place_photos (group_id);

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

create or replace function public.is_place_member(target_place_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.places p
    join public.group_members gm on gm.group_id = p.group_id
    where p.id = target_place_id
      and gm.profile_id = auth.uid()
  );
$$;

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

  select id into owner_profile_id
  from public.profiles
  where lower(email) = lower(owner_email)
  limit 1;

  if owner_profile_id is null then
    raise exception 'Perfil com email % nao encontrado em public.profiles', owner_email;
  end if;

  select id into partner_profile_id
  from public.profiles
  where lower(email) = lower(partner_email)
  limit 1;

  if partner_profile_id is null then
    raise exception 'Perfil com email % nao encontrado em public.profiles', partner_email;
  end if;

  select g.id into new_group_id
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

revoke all on function public.set_active_group(uuid) from public;
grant execute on function public.set_active_group(uuid) to authenticated, service_role;
revoke all on function public.seed_couple_group(text, text, text, text, text) from public;
grant execute on function public.seed_couple_group(text, text, text, text, text) to authenticated, service_role;
revoke all on function public.seed_filipe_victor(text, text) from public;
grant execute on function public.seed_filipe_victor(text, text) to authenticated, service_role;

-- RLS policies for auth-backed resources.
alter table public.profiles enable row level security;
alter table public.groups enable row level security;
alter table public.group_members enable row level security;
alter table public.places enable row level security;
alter table public.place_photos enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
for select to authenticated using ((select auth.uid()) = id);

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own" on public.profiles
for insert to authenticated with check ((select auth.uid()) = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles
for update to authenticated
using ((select auth.uid()) = id)
with check ((select auth.uid()) = id);

drop policy if exists "profiles_delete_own" on public.profiles;
create policy "profiles_delete_own" on public.profiles
for delete to authenticated using ((select auth.uid()) = id);

drop policy if exists "groups_select_member" on public.groups;
create policy "groups_select_member" on public.groups
for select to authenticated using (public.is_group_member(id));

drop policy if exists "groups_insert_self" on public.groups;
create policy "groups_insert_self" on public.groups
for insert to authenticated
with check (owner_id = (select auth.uid()) and created_by = (select auth.uid()));

drop policy if exists "groups_update_owner" on public.groups;
create policy "groups_update_owner" on public.groups
for update to authenticated
using (public.is_group_owner(id))
with check (public.is_group_owner(id));

drop policy if exists "groups_delete_owner" on public.groups;
create policy "groups_delete_owner" on public.groups
for delete to authenticated using (public.is_group_owner(id));

drop policy if exists "group_members_select_member" on public.group_members;
create policy "group_members_select_member" on public.group_members
for select to authenticated using (public.is_group_member(group_id));

drop policy if exists "group_members_insert_owner" on public.group_members;
create policy "group_members_insert_owner" on public.group_members
for insert to authenticated with check (public.is_group_owner(group_id));

drop policy if exists "group_members_delete_owner_or_self" on public.group_members;
create policy "group_members_delete_owner_or_self" on public.group_members
for delete to authenticated
using (public.is_group_owner(group_id) or profile_id = (select auth.uid()));

drop policy if exists "places_select_member" on public.places;
create policy "places_select_member" on public.places
for select to authenticated using (public.is_group_member(group_id));

drop policy if exists "places_insert_member" on public.places;
create policy "places_insert_member" on public.places
for insert to authenticated
with check (public.is_group_member(group_id) and created_by = (select auth.uid()));

drop policy if exists "places_update_member" on public.places;
create policy "places_update_member" on public.places
for update to authenticated
using (public.is_group_member(group_id))
with check (public.is_group_member(group_id));

drop policy if exists "places_delete_member" on public.places;
create policy "places_delete_member" on public.places
for delete to authenticated using (public.is_group_member(group_id));

drop policy if exists "place_photos_select_member" on public.place_photos;
create policy "place_photos_select_member" on public.place_photos
for select to authenticated using (public.is_group_member(group_id));

drop policy if exists "place_photos_insert_member" on public.place_photos;
create policy "place_photos_insert_member" on public.place_photos
for insert to authenticated
with check (public.is_group_member(group_id) and created_by = (select auth.uid()));

drop policy if exists "place_photos_update_member" on public.place_photos;
create policy "place_photos_update_member" on public.place_photos
for update to authenticated
using (public.is_group_member(group_id))
with check (public.is_group_member(group_id));

drop policy if exists "place_photos_delete_member" on public.place_photos;
create policy "place_photos_delete_member" on public.place_photos
for delete to authenticated using (public.is_group_member(group_id));

-- ---------------------------------------------------------------------------
-- No-auth schema: perfis, grupos, lugares, guias.
-- ---------------------------------------------------------------------------

create table if not exists public.perfis (
  id uuid primary key default gen_random_uuid(),
  nome text not null check (char_length(nome) between 1 and 120),
  email text check (email is null or char_length(email) <= 255),
  bio text check (bio is null or char_length(bio) <= 500),
  cidade text check (cidade is null or char_length(cidade) <= 80),
  foto_url text,
  foto_caminho text,
  grupo_individual_id uuid,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

alter table public.perfis
  add column if not exists nome text,
  add column if not exists email text,
  add column if not exists bio text,
  add column if not exists cidade text,
  add column if not exists foto_url text,
  add column if not exists foto_caminho text,
  add column if not exists grupo_individual_id uuid,
  add column if not exists criado_em timestamptz not null default now(),
  add column if not exists atualizado_em timestamptz not null default now();

create unique index if not exists perfis_email_lower_idx
  on public.perfis (lower(email))
  where email is not null;

create or replace function public.gerar_codigo_grupo()
returns text
language plpgsql
as $$
declare
  v_codigo text;
  v_tentativa int := 0;
begin
  loop
    v_codigo := lpad(floor(random() * 1000000)::int::text, 6, '0');
    exit when not exists (
      select 1
      from public.grupos
      where codigo = v_codigo
    );

    v_tentativa := v_tentativa + 1;
    if v_tentativa >= 20 then
      raise exception 'Nao foi possivel gerar um codigo unico de grupo';
    end if;
  end loop;

  return v_codigo;
end;
$$;

create table if not exists public.grupos (
  id uuid primary key default gen_random_uuid(),
  codigo text not null default public.gerar_codigo_grupo() check (codigo ~ '^[0-9]{6}$'),
  nome text not null check (char_length(nome) between 1 and 80),
  tipo text not null default 'casal' check (tipo in ('individual', 'casal', 'grupo')),
  descricao text check (descricao is null or char_length(descricao) <= 500),
  foto_url text,
  foto_caminho text,
  dono_perfil_id uuid references public.perfis (id) on delete set null,
  membros jsonb not null default '[]'::jsonb,
  solicitacoes jsonb not null default '[]'::jsonb,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

alter table public.grupos
  add column if not exists codigo text,
  add column if not exists nome text,
  add column if not exists tipo text,
  add column if not exists descricao text,
  add column if not exists foto_url text,
  add column if not exists foto_caminho text,
  add column if not exists dono_perfil_id uuid,
  add column if not exists membros jsonb,
  add column if not exists solicitacoes jsonb,
  add column if not exists criado_em timestamptz not null default now(),
  add column if not exists atualizado_em timestamptz not null default now();

update public.grupos set codigo = public.gerar_codigo_grupo() where codigo is null;
update public.grupos set tipo = 'casal' where tipo is null;
update public.grupos set membros = '[]'::jsonb where membros is null;
update public.grupos set solicitacoes = '[]'::jsonb where solicitacoes is null;

alter table public.grupos
  alter column codigo set not null,
  alter column codigo set default public.gerar_codigo_grupo(),
  alter column tipo set not null,
  alter column tipo set default 'casal',
  alter column membros set not null,
  alter column membros set default '[]'::jsonb,
  alter column solicitacoes set not null,
  alter column solicitacoes set default '[]'::jsonb;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'grupos_codigo_formato_check'
      and conrelid = 'public.grupos'::regclass
  ) then
    alter table public.grupos
      add constraint grupos_codigo_formato_check check (codigo ~ '^[0-9]{6}$');
  end if;
end;
$$;

create unique index if not exists grupos_codigo_idx on public.grupos (codigo);
create index if not exists grupos_dono_idx on public.grupos (dono_perfil_id);
create index if not exists grupos_membros_gin_idx on public.grupos using gin (membros);
create index if not exists grupos_solicitacoes_gin_idx on public.grupos using gin (solicitacoes);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'perfis_grupo_individual_id_fkey'
      and conrelid = 'public.perfis'::regclass
  ) then
    alter table public.perfis
      add constraint perfis_grupo_individual_id_fkey
      foreign key (grupo_individual_id)
      references public.grupos (id)
      on delete set null;
  end if;
end;
$$;

create table if not exists public.lugares (
  id uuid primary key default gen_random_uuid(),
  grupo_id uuid not null references public.grupos (id) on delete cascade,
  nome text not null check (char_length(nome) between 1 and 120),
  categoria text check (categoria is null or char_length(categoria) <= 80),
  bairro text check (bairro is null or char_length(bairro) <= 80),
  cidade text check (cidade is null or char_length(cidade) <= 80),
  faixa_preco smallint check (faixa_preco is null or faixa_preco between 1 and 4),
  link text check (link is null or char_length(link) <= 500),
  notas text check (notas is null or char_length(notas) <= 2000),
  status text not null default 'quero_ir' check (status in ('quero_ir', 'fomos', 'quero_voltar', 'nao_curti')),
  favorito boolean not null default false,
  imagem_capa text,
  fotos jsonb not null default '[]'::jsonb,
  adicionado_por text,
  adicionado_por_perfil_id uuid references public.perfis (id) on delete set null,
  extra jsonb not null default '{}'::jsonb,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

alter table public.lugares
  add column if not exists grupo_id uuid,
  add column if not exists nome text,
  add column if not exists categoria text,
  add column if not exists bairro text,
  add column if not exists cidade text,
  add column if not exists faixa_preco smallint,
  add column if not exists link text,
  add column if not exists notas text,
  add column if not exists status text,
  add column if not exists favorito boolean,
  add column if not exists imagem_capa text,
  add column if not exists fotos jsonb,
  add column if not exists adicionado_por text,
  add column if not exists adicionado_por_perfil_id uuid,
  add column if not exists extra jsonb,
  add column if not exists criado_em timestamptz not null default now(),
  add column if not exists atualizado_em timestamptz not null default now();

update public.lugares set status = 'quero_ir' where status is null;
update public.lugares set favorito = false where favorito is null;
update public.lugares set fotos = '[]'::jsonb where fotos is null;
update public.lugares set extra = '{}'::jsonb where extra is null;

alter table public.lugares
  alter column status set not null,
  alter column status set default 'quero_ir',
  alter column favorito set not null,
  alter column favorito set default false,
  alter column fotos set not null,
  alter column fotos set default '[]'::jsonb,
  alter column extra set not null,
  alter column extra set default '{}'::jsonb;

create index if not exists lugares_grupo_idx on public.lugares (grupo_id);
create index if not exists lugares_status_idx on public.lugares (grupo_id, status);
create index if not exists lugares_favorito_idx on public.lugares (grupo_id, favorito) where favorito;
create index if not exists lugares_adicionado_por_idx on public.lugares (adicionado_por_perfil_id);
create index if not exists lugares_nome_idx on public.lugares using gin (to_tsvector('portuguese', nome));

create table if not exists public.guias (
  id uuid primary key default gen_random_uuid(),
  grupo_id uuid not null references public.grupos (id) on delete cascade,
  nome text not null check (char_length(nome) between 1 and 80),
  descricao text check (descricao is null or char_length(descricao) <= 500),
  lugar_ids jsonb not null default '[]'::jsonb,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

alter table public.guias
  add column if not exists grupo_id uuid,
  add column if not exists nome text,
  add column if not exists descricao text,
  add column if not exists lugar_ids jsonb,
  add column if not exists criado_em timestamptz not null default now(),
  add column if not exists atualizado_em timestamptz not null default now();

update public.guias set lugar_ids = '[]'::jsonb where lugar_ids is null;

alter table public.guias
  alter column lugar_ids set not null,
  alter column lugar_ids set default '[]'::jsonb;

create index if not exists guias_grupo_idx on public.guias (grupo_id);
create index if not exists guias_lugar_ids_gin_idx on public.guias using gin (lugar_ids);

drop trigger if exists trg_perfis_atualizado_em on public.perfis;
create trigger trg_perfis_atualizado_em
before update on public.perfis
for each row execute function public.atualizar_timestamp();

drop trigger if exists trg_grupos_atualizado_em on public.grupos;
create trigger trg_grupos_atualizado_em
before update on public.grupos
for each row execute function public.atualizar_timestamp();

drop trigger if exists trg_lugares_atualizado_em on public.lugares;
create trigger trg_lugares_atualizado_em
before update on public.lugares
for each row execute function public.atualizar_timestamp();

drop trigger if exists trg_guias_atualizado_em on public.guias;
create trigger trg_guias_atualizado_em
before update on public.guias
for each row execute function public.atualizar_timestamp();

alter table public.perfis disable row level security;
alter table public.grupos disable row level security;
alter table public.lugares disable row level security;
alter table public.guias disable row level security;

-- ---------------------------------------------------------------------------
-- Storage buckets used by profile, group and place/lugar photo endpoints.
-- ---------------------------------------------------------------------------

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values
  (
    'profile-photos',
    'profile-photos',
    true,
    2097152,
    array['image/jpeg', 'image/png', 'image/webp', 'image/gif']
  ),
  (
    'group-photos',
    'group-photos',
    true,
    2097152,
    array['image/jpeg', 'image/png', 'image/webp', 'image/gif']
  ),
  (
    'place-photos',
    'place-photos',
    true,
    5242880,
    array['image/jpeg', 'image/png', 'image/webp', 'image/gif']
  )
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types,
  updated_at = timezone('utc', now());

-- ---------------------------------------------------------------------------
-- Grants and PostgREST schema cache refresh.
-- ---------------------------------------------------------------------------

grant usage on schema public to anon, authenticated, service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;
grant select, insert, update, delete on table
  public.profiles,
  public.groups,
  public.group_members,
  public.places,
  public.place_photos,
  public.perfis,
  public.grupos,
  public.lugares,
  public.guias
to anon, authenticated;
grant execute on all functions in schema public to authenticated;

notify pgrst, 'reload schema';
