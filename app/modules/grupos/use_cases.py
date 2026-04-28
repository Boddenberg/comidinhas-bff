from __future__ import annotations

import logging
from typing import Any

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.grupos.schemas import (
    GrupoCreateRequest,
    GrupoListResponse,
    GrupoMembroRequest,
    GrupoResponse,
    GrupoUpdateRequest,
    MembroSchema,
    PapelMembro,
    TipoGrupo,
)

logger = logging.getLogger(__name__)


class ManageGruposUseCase:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def listar(self, *, perfil_id: str | None = None) -> GrupoListResponse:
        logger.info("grupos.listar.start perfil_id=%s", perfil_id)
        rows = await self._client.list_grupos(perfil_id=perfil_id)
        items = [self._mapear(r) for r in rows if isinstance(r, dict)]
        logger.info("grupos.listar.end perfil_id=%s total=%s", perfil_id, len(items))
        return GrupoListResponse(items=items, total=len(items))

    async def buscar(self, *, grupo_id: str) -> GrupoResponse:
        raw = await self._client.get_grupo(grupo_id=grupo_id)
        if raw is None:
            raise NotFoundError("Grupo nao encontrado.")
        return self._mapear(raw)

    async def criar(self, *, request: GrupoCreateRequest) -> GrupoResponse:
        logger.info(
            "grupos.criar.start nome=%s tipo=%s membros_input=%s dono_perfil_id=%s",
            request.nome,
            request.tipo.value,
            len(request.membros),
            request.dono_perfil_id,
        )
        membros = await self._resolver_membros(
            request.membros,
            dono_perfil_id=request.dono_perfil_id,
        )
        dono_perfil_id = request.dono_perfil_id or self._primeiro_perfil_id(membros)
        self._marcar_dono(membros=membros, dono_perfil_id=dono_perfil_id)
        self._validar_espaco(
            tipo=request.tipo,
            membros=membros,
            dono_perfil_id=dono_perfil_id,
        )

        payload: dict[str, Any] = {
            "nome": request.nome,
            "tipo": request.tipo.value,
            "descricao": request.descricao,
            "dono_perfil_id": dono_perfil_id,
            "membros": [m.model_dump(mode="json", exclude_none=True) for m in membros],
        }
        criado = await self._client.insert_grupo(payload=payload)
        response = self._mapear(criado)
        logger.info(
            "grupos.criar.end grupo_id=%s tipo=%s membros=%s",
            response.id,
            response.tipo.value,
            len(response.membros),
        )
        return response

    async def atualizar(self, *, grupo_id: str, request: GrupoUpdateRequest) -> GrupoResponse:
        logger.info("grupos.atualizar.start grupo_id=%s fields=%s", grupo_id, sorted(request.model_fields_set))
        atual = await self._client.get_grupo(grupo_id=grupo_id)
        if atual is None:
            raise NotFoundError("Grupo nao encontrado.")

        payload: dict[str, Any] = {}
        if "nome" in request.model_fields_set:
            payload["nome"] = request.nome
        if "tipo" in request.model_fields_set:
            payload["tipo"] = request.tipo.value if request.tipo else None
        if "descricao" in request.model_fields_set:
            payload["descricao"] = request.descricao
        if "dono_perfil_id" in request.model_fields_set:
            payload["dono_perfil_id"] = request.dono_perfil_id

        tipo_final = request.tipo or self._tipo_from_raw(atual.get("tipo"))
        dono_final = (
            request.dono_perfil_id
            if "dono_perfil_id" in request.model_fields_set
            else atual.get("dono_perfil_id")
        )

        if "membros" in request.model_fields_set:
            membros = await self._resolver_membros(
                request.membros or [],
                dono_perfil_id=dono_final,
            )
            self._marcar_dono(membros=membros, dono_perfil_id=dono_final)
            self._validar_espaco(
                tipo=tipo_final,
                membros=membros,
                dono_perfil_id=dono_final,
            )
            payload["membros"] = [
                m.model_dump(mode="json", exclude_none=True) for m in membros
            ]
        elif "tipo" in request.model_fields_set or "dono_perfil_id" in request.model_fields_set:
            membros = self._parse_membros(atual.get("membros"))
            if dono_final and not any(m.perfil_id == dono_final for m in membros):
                membros = await self._resolver_membros(
                    membros,
                    dono_perfil_id=dono_final,
                )
                payload["membros"] = [
                    m.model_dump(mode="json", exclude_none=True) for m in membros
                ]
            self._marcar_dono(membros=membros, dono_perfil_id=dono_final)
            self._validar_espaco(
                tipo=tipo_final,
                membros=membros,
                dono_perfil_id=dono_final,
            )

        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")

        await self._client.update_grupo(grupo_id=grupo_id, payload=payload)
        response = await self.buscar(grupo_id=grupo_id)
        logger.info("grupos.atualizar.end grupo_id=%s", grupo_id)
        return response

    async def adicionar_membro(
        self,
        *,
        grupo_id: str,
        request: GrupoMembroRequest,
    ) -> GrupoResponse:
        raw = await self._client.get_grupo(grupo_id=grupo_id)
        if raw is None:
            raise NotFoundError("Grupo nao encontrado.")

        novo = await self._resolver_membros(
            [
                MembroSchema(
                    perfil_id=request.perfil_id,
                    email=request.email,
                    papel=request.papel,
                )
            ],
        )
        membros = self._parse_membros(raw.get("membros"))
        membros = self._mesclar_membros(membros, novo)

        tipo = self._tipo_from_raw(raw.get("tipo"))
        dono_perfil_id = raw.get("dono_perfil_id") or self._primeiro_perfil_id(membros)
        self._marcar_dono(membros=membros, dono_perfil_id=dono_perfil_id)
        self._validar_espaco(
            tipo=tipo,
            membros=membros,
            dono_perfil_id=dono_perfil_id,
        )

        await self._client.update_grupo(
            grupo_id=grupo_id,
            payload={
                "dono_perfil_id": dono_perfil_id,
                "membros": [m.model_dump(mode="json", exclude_none=True) for m in membros],
            },
        )
        return await self.buscar(grupo_id=grupo_id)

    async def remover_membro(self, *, grupo_id: str, perfil_id: str) -> GrupoResponse:
        raw = await self._client.get_grupo(grupo_id=grupo_id)
        if raw is None:
            raise NotFoundError("Grupo nao encontrado.")

        membros = self._parse_membros(raw.get("membros"))
        novos_membros = [m for m in membros if m.perfil_id != perfil_id]
        if len(novos_membros) == len(membros):
            raise NotFoundError("Membro nao encontrado neste grupo.")

        tipo = self._tipo_from_raw(raw.get("tipo"))
        dono_perfil_id = raw.get("dono_perfil_id")
        if dono_perfil_id == perfil_id:
            dono_perfil_id = self._primeiro_perfil_id(novos_membros)
            for membro in novos_membros:
                membro.papel = (
                    PapelMembro.DONO
                    if membro.perfil_id == dono_perfil_id
                    else PapelMembro.MEMBRO
                )

        self._validar_espaco(
            tipo=tipo,
            membros=novos_membros,
            dono_perfil_id=dono_perfil_id,
        )
        await self._client.update_grupo(
            grupo_id=grupo_id,
            payload={
                "dono_perfil_id": dono_perfil_id,
                "membros": [
                    m.model_dump(mode="json", exclude_none=True)
                    for m in novos_membros
                ],
            },
        )
        return await self.buscar(grupo_id=grupo_id)

    async def remover(self, *, grupo_id: str) -> dict[str, Any]:
        logger.info("grupos.remover.start grupo_id=%s", grupo_id)
        raw = await self._client.get_grupo(grupo_id=grupo_id)
        if raw is None:
            raise NotFoundError("Grupo nao encontrado.")
        await self._client.delete_grupo(grupo_id=grupo_id)
        logger.info("grupos.remover.end grupo_id=%s", grupo_id)
        return {"sucesso": True, "mensagem": "Grupo removido com sucesso."}

    async def _resolver_membros(
        self,
        membros: list[MembroSchema],
        *,
        dono_perfil_id: str | None = None,
    ) -> list[MembroSchema]:
        resolvidos: list[MembroSchema] = []

        for membro in membros:
            resolvidos = self._mesclar_membros(
                resolvidos,
                [await self._resolver_membro(membro)],
            )

        if dono_perfil_id:
            perfil = await self._buscar_perfil(perfil_id=dono_perfil_id)
            resolvidos = self._mesclar_membros(
                resolvidos,
                [self._perfil_para_membro(perfil, papel=PapelMembro.DONO)],
            )
            for membro in resolvidos:
                if membro.perfil_id != dono_perfil_id and membro.papel == PapelMembro.DONO:
                    membro.papel = PapelMembro.MEMBRO

        return resolvidos

    async def _resolver_membro(self, membro: MembroSchema) -> MembroSchema:
        if membro.perfil_id:
            perfil = await self._buscar_perfil(perfil_id=membro.perfil_id)
            return self._perfil_para_membro(perfil, papel=membro.papel)

        if membro.email:
            perfil = await self._client.get_perfil_por_email(email=membro.email)
            if perfil is None:
                raise NotFoundError(f"Nao encontrei um perfil com o email {membro.email}.")
            return self._perfil_para_membro(perfil, papel=membro.papel)

        if membro.nome:
            return membro

        raise BadRequestError("Cada membro precisa ter perfil_id, email ou nome.")

    async def _buscar_perfil(self, *, perfil_id: str) -> dict[str, Any]:
        perfil = await self._client.get_perfil(perfil_id=perfil_id)
        if perfil is None:
            raise NotFoundError("Perfil nao encontrado.")
        return perfil

    @staticmethod
    def _perfil_para_membro(perfil: dict[str, Any], *, papel: PapelMembro) -> MembroSchema:
        return MembroSchema(
            perfil_id=str(perfil.get("id", "")),
            nome=perfil.get("nome"),
            email=perfil.get("email"),
            papel=papel,
        )

    @classmethod
    def _mesclar_membros(
        cls,
        atuais: list[MembroSchema],
        novos: list[MembroSchema],
    ) -> list[MembroSchema]:
        resultado = list(atuais)
        for novo in novos:
            chave_nova = cls._chave_membro(novo)
            existente = next(
                (m for m in resultado if cls._chave_membro(m) == chave_nova),
                None,
            )
            if existente is None:
                resultado.append(novo)
                continue
            existente.nome = novo.nome or existente.nome
            existente.email = novo.email or existente.email
            existente.perfil_id = novo.perfil_id or existente.perfil_id
            if novo.papel == PapelMembro.DONO:
                existente.papel = PapelMembro.DONO
        return resultado

    @staticmethod
    def _chave_membro(membro: MembroSchema) -> str:
        if membro.perfil_id:
            return f"perfil:{membro.perfil_id}"
        if membro.email:
            return f"email:{membro.email.lower()}"
        return f"nome:{(membro.nome or '').lower()}"

    @staticmethod
    def _primeiro_perfil_id(membros: list[MembroSchema]) -> str | None:
        for membro in membros:
            if membro.perfil_id:
                return membro.perfil_id
        return None

    @staticmethod
    def _marcar_dono(
        *,
        membros: list[MembroSchema],
        dono_perfil_id: str | None,
    ) -> None:
        if not dono_perfil_id:
            return
        for membro in membros:
            membro.papel = (
                PapelMembro.DONO
                if membro.perfil_id == dono_perfil_id
                else PapelMembro.MEMBRO
            )

    @staticmethod
    def _validar_espaco(
        *,
        tipo: TipoGrupo,
        membros: list[MembroSchema],
        dono_perfil_id: str | None,
    ) -> None:
        perfis = {m.perfil_id for m in membros if m.perfil_id}

        if tipo == TipoGrupo.INDIVIDUAL:
            if not dono_perfil_id or dono_perfil_id not in perfis:
                raise BadRequestError("Espaco individual precisa ter um perfil dono cadastrado.")
            if len(perfis) != 1:
                raise BadRequestError("Espaco individual deve ter somente um perfil.")

        if tipo == TipoGrupo.CASAL and len(perfis) < 2:
            raise BadRequestError("Para criar um casal, informe dois perfis cadastrados.")

        if tipo == TipoGrupo.GRUPO and not perfis:
            raise BadRequestError("Grupo precisa ter ao menos um perfil cadastrado.")

    @classmethod
    def _parse_membros(cls, raw: Any) -> list[MembroSchema]:
        if not isinstance(raw, list):
            return []

        membros: list[MembroSchema] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                membros.append(
                    MembroSchema(
                        perfil_id=item.get("perfil_id"),
                        nome=item.get("nome"),
                        email=item.get("email"),
                        papel=cls._papel_from_raw(item.get("papel")),
                    )
                )
            except Exception:
                continue
        return membros

    @classmethod
    def _mapear(cls, raw: dict[str, Any]) -> GrupoResponse:
        return GrupoResponse(
            id=str(raw.get("id", "")),
            nome=str(raw.get("nome", "")),
            tipo=cls._tipo_from_raw(raw.get("tipo")),
            descricao=raw.get("descricao"),
            dono_perfil_id=raw.get("dono_perfil_id"),
            membros=cls._parse_membros(raw.get("membros")),
            criado_em=raw.get("criado_em"),
            atualizado_em=raw.get("atualizado_em"),
        )

    @staticmethod
    def _tipo_from_raw(raw: Any) -> TipoGrupo:
        try:
            return TipoGrupo(raw or TipoGrupo.CASAL.value)
        except ValueError:
            return TipoGrupo.GRUPO

    @staticmethod
    def _papel_from_raw(raw: Any) -> PapelMembro:
        try:
            return PapelMembro(raw or PapelMembro.MEMBRO.value)
        except ValueError:
            return PapelMembro.MEMBRO
