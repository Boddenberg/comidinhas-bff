-- Align the production constraint with the current API enum.
-- The backend creates an automatic individual group for every new perfil.

alter table public.grupos
  drop constraint if exists grupos_tipo_check;

alter table public.grupos
  drop constraint if exists grupos_tipo_valid;

alter table public.grupos
  add constraint grupos_tipo_check
  check (tipo in ('individual', 'casal', 'grupo'));

-- Repair perfil rows that were inserted before the old constraint rejected
-- their automatic individual group creation.
do $$
declare
  v_perfil record;
  v_grupo_id uuid;
  v_membro jsonb;
begin
  for v_perfil in
    select p.id, p.nome, p.email
    from public.perfis p
    left join public.grupos g on g.id = p.grupo_individual_id
    where p.grupo_individual_id is null
       or g.id is null
  loop
    v_membro := jsonb_build_object(
      'perfil_id', v_perfil.id::text,
      'nome', v_perfil.nome,
      'email', v_perfil.email,
      'papel', 'dono'
    );

    insert into public.grupos (
      nome,
      tipo,
      descricao,
      dono_perfil_id,
      membros
    )
    values (
      coalesce(nullif(v_perfil.nome, ''), 'Meu perfil'),
      'individual',
      null,
      v_perfil.id,
      jsonb_build_array(v_membro)
    )
    returning id into v_grupo_id;

    update public.perfis
    set grupo_individual_id = v_grupo_id
    where id = v_perfil.id;
  end loop;
end;
$$;

notify pgrst, 'reload schema';
