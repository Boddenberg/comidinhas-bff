-- ============================================================
-- Comidinhas - "Criar guia com IA" v2
--
-- Adicoes 100% aditivas:
-- 1. Estado 'cancelled' nos jobs
-- 2. Coluna cancelled_em (quando o usuario cancela)
-- 3. Coluna parent_job_id (para retries)
-- 4. Indice util pra watchdog (jobs ativos com atualizado_em antigo)
-- ============================================================

alter table public.guia_ai_jobs
  drop constraint if exists guia_ai_jobs_status_check;

alter table public.guia_ai_jobs
  add constraint guia_ai_jobs_status_check check (status in (
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
    'failed',
    'cancelled'
  ));

alter table public.guia_ai_jobs
  add column if not exists cancelled_em timestamptz,
  add column if not exists parent_job_id uuid
    references public.guia_ai_jobs (id) on delete set null;

create index if not exists guia_ai_jobs_active_idx
  on public.guia_ai_jobs (atualizado_em)
  where status not in (
    'completed',
    'completed_with_warnings',
    'invalid_content',
    'failed',
    'cancelled'
  );

create index if not exists guia_ai_jobs_parent_idx
  on public.guia_ai_jobs (parent_job_id)
  where parent_job_id is not null;
