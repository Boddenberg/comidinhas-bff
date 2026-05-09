-- ============================================================
-- Comidinhas - Historico de sugestoes da IA
--
-- Cria a tabela `sugestoes_ia_historico` para rastrear todos os
-- restaurantes oferecidos pelos endpoints de IA (surpresa/decisao,
-- recomendacao por mensagem, "today" da home).
--
-- Objetivo:
-- - evitar repetir o mesmo restaurante no mesmo dia ou na mesma
--   semana para o mesmo grupo/perfil;
-- - alimentar o prompt da IA com sinais de personalizacao
--   (cozinhas e moods frequentes nas ultimas semanas);
-- - manter um log auditavel das escolhas e justificativas.
-- ============================================================

create table if not exists public.sugestoes_ia_historico (
  id              uuid        primary key default gen_random_uuid(),
  grupo_id        uuid        not null references public.grupos (id) on delete cascade,
  perfil_id       uuid        references public.perfis (id) on delete set null,
  lugar_id        uuid        references public.lugares (id) on delete set null,
  google_place_id text,
  nome            text        not null check (char_length(nome) between 1 and 200),
  origem          text        not null default 'comidinhas'
                              check (origem in ('comidinhas', 'google')),
  fonte           text        not null
                              check (fonte in (
                                'decidir_restaurante',
                                'recomendar_restaurantes',
                                'today_recommendations'
                              )),
  posicao         smallint    not null default 1 check (posicao >= 1),
  criterios       jsonb       not null default '{}'::jsonb,
  motivo          text        check (motivo is null or char_length(motivo) <= 1200),
  modelo          text        check (modelo is null or char_length(modelo) <= 80),
  criado_em       timestamptz not null default now()
);

create index if not exists sugestoes_ia_historico_grupo_idx
  on public.sugestoes_ia_historico (grupo_id, criado_em desc);

create index if not exists sugestoes_ia_historico_lugar_idx
  on public.sugestoes_ia_historico (lugar_id)
  where lugar_id is not null;

create index if not exists sugestoes_ia_historico_google_idx
  on public.sugestoes_ia_historico (grupo_id, google_place_id, criado_em desc)
  where google_place_id is not null;

create index if not exists sugestoes_ia_historico_fonte_idx
  on public.sugestoes_ia_historico (grupo_id, fonte, criado_em desc);

alter table public.sugestoes_ia_historico disable row level security;
