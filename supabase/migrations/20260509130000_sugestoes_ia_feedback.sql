-- ============================================================
-- Comidinhas - Feedback das sugestoes da IA + config por grupo
--
-- Aditiva: nao remove dados. Idempotente.
--
-- 1. Colunas de feedback em `sugestoes_ia_historico`:
--    - feedback ('aceito' | 'recusado' | 'fui')
--    - feedback_comentario (texto livre curto)
--    - feedback_em (timestamp da resposta)
--
-- 2. Coluna `preferencias_ia` em `grupos` para configuracao
--    leve por grupo (ex.: janela de dias para nao repetir).
-- ============================================================

alter table public.sugestoes_ia_historico
  add column if not exists feedback text
    check (feedback is null or feedback in ('aceito', 'recusado', 'fui')),
  add column if not exists feedback_comentario text
    check (feedback_comentario is null or char_length(feedback_comentario) <= 500),
  add column if not exists feedback_em timestamptz,
  add column if not exists categoria text
    check (categoria is null or char_length(categoria) <= 80),
  add column if not exists bairro text
    check (bairro is null or char_length(bairro) <= 80);

create index if not exists sugestoes_ia_historico_feedback_idx
  on public.sugestoes_ia_historico (grupo_id, feedback, feedback_em desc)
  where feedback is not null;

alter table public.grupos
  add column if not exists preferencias_ia jsonb not null default '{}'::jsonb;
