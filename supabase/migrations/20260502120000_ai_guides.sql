-- ============================================================
-- Comidinhas - feature "Criar guia com IA"
--
-- Adicoes 100% aditivas:
-- 1. Colunas opcionais em public.guias para metadados de
--    importacao por IA (mantem retrocompatibilidade total
--    com guias manuais ja existentes).
-- 2. Tabela public.guia_itens com dados ricos por item
--    importado (posicao, place_id, lat/lng, telefone, etc).
-- 3. Tabela public.guia_ai_jobs com a maquina de estados
--    do processamento desacoplado da request.
--
-- Nenhuma coluna ou tabela existente e removida ou alterada
-- de forma destrutiva. Todas as colunas novas tem default
-- seguro para que linhas antigas continuem validas.
-- ============================================================

-- ----------------------------------------------------------------
-- 1. Colunas opcionais na tabela guias
-- ----------------------------------------------------------------
alter table public.guias
  add column if not exists tipo_guia text not null default 'manual'
    check (tipo_guia in ('manual', 'ia')),
  add column if not exists fonte text
    check (fonte is null or char_length(fonte) <= 200),
  add column if not exists autor text
    check (autor is null or char_length(autor) <= 200),
  add column if not exists url_origem text
    check (url_origem is null or char_length(url_origem) <= 1000),
  add column if not exists data_publicacao timestamptz,
  add column if not exists categoria text
    check (categoria is null or char_length(categoria) <= 80),
  add column if not exists regiao text
    check (regiao is null or char_length(regiao) <= 80),
  add column if not exists cidade_principal text
    check (cidade_principal is null or char_length(cidade_principal) <= 80),
  add column if not exists imagem_capa text,
  add column if not exists total_itens integer not null default 0
    check (total_itens >= 0),
  add column if not exists status_importacao text
    check (status_importacao is null or status_importacao in (
      'pendente',
      'processando',
      'completo',
      'completo_com_alertas',
      'criado_com_pendencias',
      'baixa_confianca',
      'invalido',
      'falhou'
    )),
  add column if not exists qualidade_importacao text
    check (qualidade_importacao is null or qualidade_importacao in ('alta', 'media', 'baixa')),
  add column if not exists hash_texto text
    check (hash_texto is null or char_length(hash_texto) <= 128),
  add column if not exists alertas jsonb not null default '[]'::jsonb,
  add column if not exists sugestoes jsonb not null default '{}'::jsonb,
  add column if not exists metadados jsonb not null default '{}'::jsonb;

create index if not exists guias_tipo_idx on public.guias (tipo_guia);
create index if not exists guias_categoria_idx on public.guias (categoria);
create index if not exists guias_hash_texto_idx on public.guias (grupo_id, hash_texto)
  where hash_texto is not null;

-- ----------------------------------------------------------------
-- 2. Itens detalhados de um guia (1-N)
-- ----------------------------------------------------------------
create table if not exists public.guia_itens (
  id                       uuid        primary key default gen_random_uuid(),
  guia_id                  uuid        not null references public.guias (id) on delete cascade,
  lugar_id                 uuid        references public.lugares (id) on delete set null,
  posicao_ranking          integer,
  ordem                    integer     not null default 0,
  nome_importado           text        not null check (char_length(nome_importado) between 1 and 200),
  nome_normalizado         text,
  bairro                   text,
  cidade                   text,
  estado                   text,
  categoria                text,
  place_id                 text,
  endereco                 text,
  latitude                 double precision,
  longitude                double precision,
  google_maps_uri          text,
  telefone                 text,
  site                     text,
  rating                   numeric(3,2),
  total_avaliacoes         integer,
  preco_nivel              smallint,
  foto_url                 text,
  foto_atribuicao          text,
  status_negocio           text,
  horarios                 jsonb       not null default '[]'::jsonb,
  status_matching          text        not null default 'pendente'
                           check (status_matching in (
                             'encontrado_interno',
                             'encontrado_google',
                             'criado_automaticamente',
                             'possivel_duplicado',
                             'pendente',
                             'nao_encontrado',
                             'baixa_confianca',
                             'possivelmente_fechado',
                             'dados_incompletos',
                             'ignorado',
                             'confirmado_usuario'
                           )),
  score_matching           numeric(4,3),
  confianca_extracao       numeric(4,3),
  confianca_enriquecimento numeric(4,3),
  alertas                  jsonb       not null default '[]'::jsonb,
  trecho_original          text,
  extra                    jsonb       not null default '{}'::jsonb,
  criado_em                timestamptz not null default now(),
  atualizado_em            timestamptz not null default now()
);

create index if not exists guia_itens_guia_idx on public.guia_itens (guia_id);
create index if not exists guia_itens_lugar_idx on public.guia_itens (lugar_id);
create index if not exists guia_itens_place_id_idx on public.guia_itens (place_id);
create index if not exists guia_itens_status_idx on public.guia_itens (guia_id, status_matching);
create index if not exists guia_itens_ordem_idx on public.guia_itens (guia_id, ordem);

drop trigger if exists trg_guia_itens_atualizado_em on public.guia_itens;
create trigger trg_guia_itens_atualizado_em
  before update on public.guia_itens
  for each row execute function public.atualizar_timestamp();

alter table public.guia_itens disable row level security;

-- ----------------------------------------------------------------
-- 3. Jobs de importacao por IA
-- ----------------------------------------------------------------
create table if not exists public.guia_ai_jobs (
  id                     uuid        primary key default gen_random_uuid(),
  grupo_id               uuid        not null references public.grupos (id) on delete cascade,
  perfil_id              uuid        references public.perfis (id) on delete set null,
  guia_id                uuid        references public.guias (id) on delete set null,
  status                 text        not null default 'created'
                         check (status in (
                           'created',
                           'sanitizing_text',
                           'classifying_content',
                           'extracting_guide_metadata',
                           'extracting_restaurants',
                           'matching_internal_restaurants',
                           'searching_google_places',
                           'enriching_places',
                           'selecting_photos',
                           'calculating_group_suggestions',
                           'creating_guide',
                           'completed',
                           'completed_with_warnings',
                           'invalid_content',
                           'failed'
                         )),
  etapa_atual            text,
  etapas_concluidas      jsonb       not null default '[]'::jsonb,
  progresso_percentual   smallint    not null default 0
                         check (progresso_percentual between 0 and 100),
  texto_original         text        not null,
  texto_hash             text,
  url_origem             text,
  resultado              jsonb       not null default '{}'::jsonb,
  mensagem_usuario       text,
  motivo_invalido        text,
  alertas                jsonb       not null default '[]'::jsonb,
  tentativas             smallint    not null default 0,
  max_tentativas         smallint    not null default 3,
  logs                   jsonb       not null default '[]'::jsonb,
  estatisticas           jsonb       not null default '{}'::jsonb,
  iniciado_em            timestamptz,
  concluido_em           timestamptz,
  criado_em              timestamptz not null default now(),
  atualizado_em          timestamptz not null default now()
);

create index if not exists guia_ai_jobs_grupo_idx on public.guia_ai_jobs (grupo_id);
create index if not exists guia_ai_jobs_status_idx on public.guia_ai_jobs (status);
create index if not exists guia_ai_jobs_guia_idx on public.guia_ai_jobs (guia_id);
create index if not exists guia_ai_jobs_hash_idx on public.guia_ai_jobs (grupo_id, texto_hash)
  where texto_hash is not null;

drop trigger if exists trg_guia_ai_jobs_atualizado_em on public.guia_ai_jobs;
create trigger trg_guia_ai_jobs_atualizado_em
  before update on public.guia_ai_jobs
  for each row execute function public.atualizar_timestamp();

alter table public.guia_ai_jobs disable row level security;
