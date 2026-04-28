-- ============================================================
-- Grupos: codigo curto, foto, administradores e solicitacoes.
-- Execute no SQL Editor do Supabase para atualizar um banco no-auth existente.
-- ============================================================

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

alter table public.grupos
  add column if not exists codigo text,
  add column if not exists foto_url text,
  add column if not exists foto_caminho text,
  add column if not exists solicitacoes jsonb not null default '[]'::jsonb;

do $$
declare
  v_grupo record;
begin
  for v_grupo in
    select id
    from public.grupos
    where codigo is null
  loop
    update public.grupos
    set codigo = public.gerar_codigo_grupo()
    where id = v_grupo.id;
  end loop;
end;
$$;

alter table public.grupos
  alter column codigo set not null,
  alter column codigo set default public.gerar_codigo_grupo();

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
create index if not exists grupos_solicitacoes_gin_idx on public.grupos using gin (solicitacoes);
