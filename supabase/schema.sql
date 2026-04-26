-- ============================================================
-- Comidinhas — Schema principal (sem autenticação)
-- Aplica limpo: dropa tudo e recria com estrutura simplificada
-- ============================================================

-- 1. Remove tabelas antigas (ordem importa por causa das FKs)
DROP TABLE IF EXISTS public.place_photos  CASCADE;
DROP TABLE IF EXISTS public.places        CASCADE;
DROP TABLE IF EXISTS public.group_members CASCADE;
DROP TABLE IF EXISTS public.groups        CASCADE;

-- Remove coluna legada de profiles (se existir)
ALTER TABLE public.profiles
  DROP COLUMN IF EXISTS active_group_id;

-- ============================================================
-- 2. Tabela: grupos
-- Cada grupo é um "espaço compartilhado" (casal ou grupo de amigos).
-- Membros ficam embutidos como JSON — sem tabela separada.
-- ============================================================
CREATE TABLE IF NOT EXISTS public.grupos (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  nome         text        NOT NULL CHECK (char_length(nome) BETWEEN 1 AND 80),
  tipo         text        NOT NULL DEFAULT 'casal'
                           CHECK (tipo IN ('casal', 'grupo')),
  descricao    text        CHECK (descricao IS NULL OR char_length(descricao) <= 500),
  membros      jsonb       NOT NULL DEFAULT '[]',
  -- cada membro: {"nome": "Filipe", "email": "filipe@..."}
  criado_em    timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- 3. Tabela: lugares
-- Restaurantes / bares / cafés do grupo.
-- Fotos ficam embutidas como JSON — sem tabela separada.
-- ============================================================
CREATE TABLE IF NOT EXISTS public.lugares (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  grupo_id      uuid        NOT NULL REFERENCES public.grupos (id) ON DELETE CASCADE,
  nome          text        NOT NULL CHECK (char_length(nome) BETWEEN 1 AND 120),
  categoria     text        CHECK (categoria IS NULL OR char_length(categoria) <= 80),
  bairro        text        CHECK (bairro IS NULL OR char_length(bairro) <= 80),
  cidade        text        CHECK (cidade IS NULL OR char_length(cidade) <= 80),
  faixa_preco   smallint    CHECK (faixa_preco IS NULL OR faixa_preco BETWEEN 1 AND 4),
  link          text        CHECK (link IS NULL OR char_length(link) <= 500),
  notas         text        CHECK (notas IS NULL OR char_length(notas) <= 2000),
  status        text        NOT NULL DEFAULT 'quero_ir'
                            CHECK (status IN ('quero_ir', 'fomos', 'quero_voltar', 'nao_curti')),
  favorito      boolean     NOT NULL DEFAULT false,
  imagem_capa   text,       -- URL pública da foto de capa (espelho de fotos[x].url onde capa=true)
  fotos         jsonb       NOT NULL DEFAULT '[]',
  -- cada foto: {"id": "uuid", "url": "https://...", "caminho": "grupos/.../file.jpg", "ordem": 0, "capa": true}
  adicionado_por text,      -- nome livre de quem adicionou (ex: "Filipe")
  extra         jsonb       NOT NULL DEFAULT '{}',
  -- dados extras: {"google_place_id": "...", "avaliacao_google": 4.5, "tipos": ["restaurant"]}
  criado_em     timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now()
);

-- Índices úteis
CREATE INDEX IF NOT EXISTS lugares_grupo_idx     ON public.lugares (grupo_id);
CREATE INDEX IF NOT EXISTS lugares_status_idx    ON public.lugares (grupo_id, status);
CREATE INDEX IF NOT EXISTS lugares_favorito_idx  ON public.lugares (grupo_id, favorito) WHERE favorito;
CREATE INDEX IF NOT EXISTS lugares_nome_idx      ON public.lugares USING gin (to_tsvector('portuguese', nome));

-- ============================================================
-- 4. Trigger: atualiza atualizado_em automaticamente
-- ============================================================
CREATE OR REPLACE FUNCTION public.atualizar_timestamp()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.atualizado_em = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_grupos_atualizado_em   ON public.grupos;
DROP TRIGGER IF EXISTS trg_lugares_atualizado_em  ON public.lugares;

CREATE TRIGGER trg_grupos_atualizado_em
  BEFORE UPDATE ON public.grupos
  FOR EACH ROW EXECUTE FUNCTION public.atualizar_timestamp();

CREATE TRIGGER trg_lugares_atualizado_em
  BEFORE UPDATE ON public.lugares
  FOR EACH ROW EXECUTE FUNCTION public.atualizar_timestamp();

-- ============================================================
-- 5. Desabilita RLS (app sem autenticação — service role key)
-- ============================================================
ALTER TABLE public.grupos  DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.lugares DISABLE ROW LEVEL SECURITY;

-- ============================================================
-- 6. Função home_summary — agrega dados para a tela inicial
-- ============================================================
CREATE OR REPLACE FUNCTION public.home_summary(
  p_grupo_id  uuid,
  p_top_limit int DEFAULT 5
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_grupo       jsonb;
  v_contadores  jsonb;
  v_favoritos   jsonb;
  v_recentes    jsonb;
  v_quero_ir    jsonb;
  v_quero_voltar jsonb;
BEGIN
  -- Grupo
  SELECT to_jsonb(g) INTO v_grupo
  FROM public.grupos g
  WHERE g.id = p_grupo_id;

  IF v_grupo IS NULL THEN
    RETURN jsonb_build_object('erro', 'Grupo não encontrado');
  END IF;

  -- Contadores
  SELECT jsonb_build_object(
    'total',       COUNT(*),
    'visitados',   COUNT(*) FILTER (WHERE status IN ('fomos', 'quero_voltar', 'nao_curti')),
    'favoritos',   COUNT(*) FILTER (WHERE favorito),
    'quero_ir',    COUNT(*) FILTER (WHERE status = 'quero_ir'),
    'quero_voltar', COUNT(*) FILTER (WHERE status = 'quero_voltar')
  ) INTO v_contadores
  FROM public.lugares
  WHERE grupo_id = p_grupo_id;

  -- Top favoritos
  SELECT jsonb_agg(row_to_json(l)) INTO v_favoritos
  FROM (
    SELECT id, nome, categoria, bairro, cidade, faixa_preco,
           status, favorito, imagem_capa, adicionado_por, criado_em
    FROM public.lugares
    WHERE grupo_id = p_grupo_id AND favorito = true
    ORDER BY criado_em DESC
    LIMIT p_top_limit
  ) l;

  -- Adicionados recentemente
  SELECT jsonb_agg(row_to_json(l)) INTO v_recentes
  FROM (
    SELECT id, nome, categoria, bairro, cidade, faixa_preco,
           status, favorito, imagem_capa, adicionado_por, criado_em
    FROM public.lugares
    WHERE grupo_id = p_grupo_id
    ORDER BY criado_em DESC
    LIMIT p_top_limit
  ) l;

  -- Lista quero_ir
  SELECT jsonb_agg(row_to_json(l)) INTO v_quero_ir
  FROM (
    SELECT id, nome, categoria, bairro, cidade, faixa_preco,
           status, favorito, imagem_capa, adicionado_por, criado_em
    FROM public.lugares
    WHERE grupo_id = p_grupo_id AND status = 'quero_ir'
    ORDER BY criado_em DESC
    LIMIT p_top_limit
  ) l;

  -- Lista quero_voltar
  SELECT jsonb_agg(row_to_json(l)) INTO v_quero_voltar
  FROM (
    SELECT id, nome, categoria, bairro, cidade, faixa_preco,
           status, favorito, imagem_capa, adicionado_por, criado_em
    FROM public.lugares
    WHERE grupo_id = p_grupo_id AND status = 'quero_voltar'
    ORDER BY criado_em DESC
    LIMIT p_top_limit
  ) l;

  RETURN jsonb_build_object(
    'grupo',        v_grupo,
    'contadores',   v_contadores,
    'favoritos',    COALESCE(v_favoritos, '[]'::jsonb),
    'recentes',     COALESCE(v_recentes, '[]'::jsonb),
    'quero_ir',     COALESCE(v_quero_ir, '[]'::jsonb),
    'quero_voltar', COALESCE(v_quero_voltar, '[]'::jsonb)
  );
END;
$$;
