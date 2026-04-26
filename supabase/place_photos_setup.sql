-- ============================================================
-- Comidinhas BFF - Setup de fotos de lugares
-- Rode apos groups_places_setup.sql.
-- ============================================================

-- 1. Tabela de fotos de lugares
create table if not exists public.place_photos (
  id uuid primary key default gen_random_uuid(),
  place_id uuid not null references public.places (id) on delete cascade,
  group_id uuid not null references public.groups (id) on delete cascade,
  storage_path text not null,
  public_url text not null,
  is_cover boolean not null default false,
  sort_order smallint not null default 0,
  created_by uuid not null references public.profiles (id) on delete cascade,
  created_at timestamptz not null default timezone('utc', now()),
  constraint place_photos_sort_order_valid check (sort_order >= 0)
);

create index if not exists place_photos_place_idx on public.place_photos (place_id, sort_order);
create index if not exists place_photos_cover_idx on public.place_photos (place_id, is_cover) where is_cover;
create index if not exists place_photos_group_idx on public.place_photos (group_id);


-- 2. Funcao auxiliar de RLS: verifica se usuario e membro do grupo dono do lugar
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


-- 3. RLS - place_photos
alter table public.place_photos enable row level security;

drop policy if exists "place_photos_select_member" on public.place_photos;
create policy "place_photos_select_member"
on public.place_photos
for select
to authenticated
using (public.is_group_member(group_id));

drop policy if exists "place_photos_insert_member" on public.place_photos;
create policy "place_photos_insert_member"
on public.place_photos
for insert
to authenticated
with check (
  public.is_group_member(group_id)
  and created_by = (select auth.uid())
);

drop policy if exists "place_photos_update_member" on public.place_photos;
create policy "place_photos_update_member"
on public.place_photos
for update
to authenticated
using (public.is_group_member(group_id))
with check (public.is_group_member(group_id));

drop policy if exists "place_photos_delete_member" on public.place_photos;
create policy "place_photos_delete_member"
on public.place_photos
for delete
to authenticated
using (public.is_group_member(group_id));


-- 4. Bucket de fotos de lugares
insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
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


-- 5. RLS do bucket place-photos
-- path esperado: {group_id}/{place_id}/{uuid}.ext

drop policy if exists "place_photos_bucket_select" on storage.objects;
create policy "place_photos_bucket_select"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'place-photos'
  and public.is_group_member((storage.foldername(name))[1]::uuid)
);

drop policy if exists "place_photos_bucket_insert" on storage.objects;
create policy "place_photos_bucket_insert"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'place-photos'
  and public.is_group_member((storage.foldername(name))[1]::uuid)
);

drop policy if exists "place_photos_bucket_update" on storage.objects;
create policy "place_photos_bucket_update"
on storage.objects
for update
to authenticated
using (
  bucket_id = 'place-photos'
  and public.is_group_member((storage.foldername(name))[1]::uuid)
)
with check (
  bucket_id = 'place-photos'
  and public.is_group_member((storage.foldername(name))[1]::uuid)
);

drop policy if exists "place_photos_bucket_delete" on storage.objects;
create policy "place_photos_bucket_delete"
on storage.objects
for delete
to authenticated
using (
  bucket_id = 'place-photos'
  and public.is_group_member((storage.foldername(name))[1]::uuid)
);
