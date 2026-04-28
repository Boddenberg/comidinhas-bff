-- ============================================================
-- Comidinhas - schema principal sem autenticacao
-- Aplica limpo: dropa tudo e recria a estrutura no-auth.
-- ============================================================

create extension if not exists pgcrypto;

-- 1. Remove tabelas antigas (ordem importa por causa das FKs)
drop table if exists public.place_photos cascade;
drop table if exists public.places cascade;
drop table if exists public.group_members cascade;
drop table if exists public.groups cascade;
drop table if exists public.guias cascade;
drop table if exists public.lugares cascade;
drop table if exists public.grupos cascade;
drop table if exists public.perfis cascade;

-- ============================================================
-- 2. Tabela: perfis
-- Cada cadastro individual vira um perfil e ganha um espaco
-- individual em public.grupos.
-- ============================================================
create table public.perfis (
  id                  uuid        primary key default gen_random_uuid(),
  nome                text        not null check (char_length(nome) between 1 and 120),
  email               text        check (email is null or char_length(email) <= 255),
  bio                 text        check (bio is null or char_length(bio) <= 500),
  cidade              text        check (cidade is null or char_length(cidade) <= 80),
  foto_url            text,
  foto_caminho        text,
  grupo_individual_id uuid,
  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now()
);

create unique index perfis_email_lower_idx
  on public.perfis (lower(email))
  where email is not null;

-- ============================================================
-- 3. Tabela: grupos
-- Um grupo e o contexto selecionavel do app:
-- - individual: apenas uma pessoa
-- - casal: duas pessoas
-- - grupo: tres ou mais pessoas, ou um grupo flexivel
--
-- Membros ficam embutidos em JSON para manter o modelo no-auth
-- simples. Exemplo:
-- {"perfil_id":"uuid","nome":"Filipe","email":"filipe@...","papel":"dono"}
-- ============================================================
create table public.grupos (
  id              uuid        primary key default gen_random_uuid(),
  nome            text        not null check (char_length(nome) between 1 and 80),
  tipo            text        not null default 'casal'
                              check (tipo in ('individual', 'casal', 'grupo')),
  descricao       text        check (descricao is null or char_length(descricao) <= 500),
  dono_perfil_id  uuid        references public.perfis (id) on delete set null,
  membros         jsonb       not null default '[]'::jsonb,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);

create index grupos_dono_idx on public.grupos (dono_perfil_id);
create index grupos_membros_gin_idx on public.grupos using gin (membros);

alter table public.perfis
  add constraint perfis_grupo_individual_id_fkey
  foreign key (grupo_individual_id)
  references public.grupos (id)
  on delete set null;

-- ============================================================
-- 4. Tabela: lugares
-- Restaurantes / bares / cafes do contexto selecionado.
-- ============================================================
create table public.lugares (
  id                         uuid        primary key default gen_random_uuid(),
  grupo_id                   uuid        not null references public.grupos (id) on delete cascade,
  nome                       text        not null check (char_length(nome) between 1 and 120),
  categoria                  text        check (categoria is null or char_length(categoria) <= 80),
  bairro                     text        check (bairro is null or char_length(bairro) <= 80),
  cidade                     text        check (cidade is null or char_length(cidade) <= 80),
  faixa_preco                smallint    check (faixa_preco is null or faixa_preco between 1 and 4),
  link                       text        check (link is null or char_length(link) <= 500),
  notas                      text        check (notas is null or char_length(notas) <= 2000),
  status                     text        not null default 'quero_ir'
                                          check (status in ('quero_ir', 'fomos', 'quero_voltar', 'nao_curti')),
  favorito                   boolean     not null default false,
  imagem_capa                text,
  fotos                      jsonb       not null default '[]'::jsonb,
  adicionado_por             text,
  adicionado_por_perfil_id   uuid        references public.perfis (id) on delete set null,
  extra                      jsonb       not null default '{}'::jsonb,
  criado_em                  timestamptz not null default now(),
  atualizado_em              timestamptz not null default now()
);

create index lugares_grupo_idx on public.lugares (grupo_id);
create index lugares_status_idx on public.lugares (grupo_id, status);
create index lugares_favorito_idx on public.lugares (grupo_id, favorito) where favorito;
create index lugares_adicionado_por_idx on public.lugares (adicionado_por_perfil_id);
create index lugares_nome_idx on public.lugares using gin (to_tsvector('portuguese', nome));

-- ============================================================
-- 5. Tabela: guias
-- Guias sao colecoes customizadas de lugares dentro de um contexto.
-- A ordem dos restaurantes e preservada em lugar_ids.
-- ============================================================
create table public.guias (
  id              uuid        primary key default gen_random_uuid(),
  grupo_id        uuid        not null references public.grupos (id) on delete cascade,
  nome            text        not null check (char_length(nome) between 1 and 80),
  descricao       text        check (descricao is null or char_length(descricao) <= 500),
  lugar_ids       jsonb       not null default '[]'::jsonb,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now()
);

create index guias_grupo_idx on public.guias (grupo_id);
create index guias_lugar_ids_gin_idx on public.guias using gin (lugar_ids);

-- ============================================================
-- 6. Trigger: atualiza atualizado_em automaticamente
-- ============================================================
create or replace function public.atualizar_timestamp()
returns trigger language plpgsql as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

create trigger trg_perfis_atualizado_em
  before update on public.perfis
  for each row execute function public.atualizar_timestamp();

create trigger trg_grupos_atualizado_em
  before update on public.grupos
  for each row execute function public.atualizar_timestamp();

create trigger trg_lugares_atualizado_em
  before update on public.lugares
  for each row execute function public.atualizar_timestamp();

create trigger trg_guias_atualizado_em
  before update on public.guias
  for each row execute function public.atualizar_timestamp();

-- ============================================================
-- 7. Desabilita RLS (app sem autenticacao, usando service role)
-- ============================================================
alter table public.perfis disable row level security;
alter table public.grupos disable row level security;
alter table public.lugares disable row level security;
alter table public.guias disable row level security;

-- ============================================================
-- 8. Funcao home_summary - agregado para a tela inicial
-- ============================================================
create or replace function public.home_summary(
  p_grupo_id uuid,
  p_top_limit int default 5
)
returns jsonb
language plpgsql
security definer
as $$
declare
  v_grupo        jsonb;
  v_contadores   jsonb;
  v_favoritos    jsonb;
  v_recentes     jsonb;
  v_quero_ir     jsonb;
  v_quero_voltar jsonb;
begin
  select to_jsonb(g) into v_grupo
  from public.grupos g
  where g.id = p_grupo_id;

  if v_grupo is null then
    return jsonb_build_object('erro', 'Grupo nao encontrado');
  end if;

  select jsonb_build_object(
    'total', count(*),
    'visitados', count(*) filter (where status in ('fomos', 'quero_voltar', 'nao_curti')),
    'favoritos', count(*) filter (where favorito),
    'quero_ir', count(*) filter (where status = 'quero_ir'),
    'quero_voltar', count(*) filter (where status = 'quero_voltar')
  ) into v_contadores
  from public.lugares
  where grupo_id = p_grupo_id;

  select jsonb_agg(row_to_json(l)) into v_favoritos
  from (
    select id, nome, categoria, bairro, cidade, faixa_preco,
           status, favorito, imagem_capa, adicionado_por,
           adicionado_por_perfil_id, criado_em
    from public.lugares
    where grupo_id = p_grupo_id and favorito = true
    order by criado_em desc
    limit p_top_limit
  ) l;

  select jsonb_agg(row_to_json(l)) into v_recentes
  from (
    select id, nome, categoria, bairro, cidade, faixa_preco,
           status, favorito, imagem_capa, adicionado_por,
           adicionado_por_perfil_id, criado_em
    from public.lugares
    where grupo_id = p_grupo_id
    order by criado_em desc
    limit p_top_limit
  ) l;

  select jsonb_agg(row_to_json(l)) into v_quero_ir
  from (
    select id, nome, categoria, bairro, cidade, faixa_preco,
           status, favorito, imagem_capa, adicionado_por,
           adicionado_por_perfil_id, criado_em
    from public.lugares
    where grupo_id = p_grupo_id and status = 'quero_ir'
    order by criado_em desc
    limit p_top_limit
  ) l;

  select jsonb_agg(row_to_json(l)) into v_quero_voltar
  from (
    select id, nome, categoria, bairro, cidade, faixa_preco,
           status, favorito, imagem_capa, adicionado_por,
           adicionado_por_perfil_id, criado_em
    from public.lugares
    where grupo_id = p_grupo_id and status = 'quero_voltar'
    order by criado_em desc
    limit p_top_limit
  ) l;

  return jsonb_build_object(
    'grupo', v_grupo,
    'contadores', v_contadores,
    'favoritos', coalesce(v_favoritos, '[]'::jsonb),
    'recentes', coalesce(v_recentes, '[]'::jsonb),
    'quero_ir', coalesce(v_quero_ir, '[]'::jsonb),
    'quero_voltar', coalesce(v_quero_voltar, '[]'::jsonb)
  );
end;
$$;
