-- ============================================================
-- No-auth migration: torna created_by nullable e ajusta triggers
-- Execute no SQL Editor do Supabase.
-- ============================================================

-- 1. Remove NOT NULL de created_by em todas as tabelas relevantes
ALTER TABLE public.groups      ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE public.places      ALTER COLUMN created_by DROP NOT NULL;
ALTER TABLE public.place_photos ALTER COLUMN created_by DROP NOT NULL;

-- 2. Ajusta o trigger de insert para nao sobrescrever created_by
--    caso o valor ja tenha sido fornecido explicitamente
CREATE OR REPLACE FUNCTION public.set_audit_on_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  IF NEW.created_by IS NULL THEN
    NEW.created_by := auth.uid();
  END IF;
  RETURN NEW;
END;
$$;
