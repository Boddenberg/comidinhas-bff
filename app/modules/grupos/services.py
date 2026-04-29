from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urljoin
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.modules.grupos.mappers import GrupoMapper
from app.modules.grupos.policies import GrupoPolicy
from app.modules.grupos.repositories import GruposGateway
from app.modules.grupos.schemas import (
    GrupoCreateRequest,
    GrupoConviteResponse,
    GrupoListResponse,
    GrupoMembroRequest,
    GrupoResponse,
    GrupoUpdateRequest,
    MembroSchema,
    PapelMembro,
    PapelMembroUpdateRequest,
    ResponderSolicitacaoGrupoRequest,
    SolicitacaoEntradaGrupoListResponse,
    SolicitacaoEntradaGrupoRequest,
    SolicitacaoEntradaGrupoSchema,
    StatusSolicitacaoGrupo,
    TipoGrupo,
)

logger = logging.getLogger(__name__)

_TIPOS_IMAGEM = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class GrupoReader:
    def __init__(self, gateway: GruposGateway) -> None:
        self._gateway = gateway

    async def buscar_raw(self, *, grupo_id: str) -> dict[str, Any]:
        raw = await self._gateway.get_grupo(grupo_id=grupo_id)
        if raw is None:
            raise NotFoundError("Grupo nao encontrado.")
        return raw

    async def buscar_por_codigo_raw(self, *, codigo: str) -> dict[str, Any]:
        raw = await self._gateway.get_grupo_por_codigo(codigo=codigo)
        if raw is None:
            raise NotFoundError("Grupo nao encontrado com este codigo.")
        return raw


class GrupoMemberResolver:
    def __init__(
        self,
        gateway: GruposGateway,
        mapper: type[GrupoMapper] = GrupoMapper,
    ) -> None:
        self._gateway = gateway
        self._mapper = mapper

    async def resolver_membros(
        self,
        membros: list[MembroSchema],
        *,
        dono_perfil_id: str | None = None,
    ) -> list[MembroSchema]:
        resolvidos: list[MembroSchema] = []

        for membro in membros:
            resolvidos = self.mesclar_membros(
                resolvidos,
                [await self.resolver_membro(membro)],
            )

        if dono_perfil_id:
            perfil = await self.buscar_perfil(perfil_id=dono_perfil_id)
            resolvidos = self.mesclar_membros(
                resolvidos,
                [self._mapper.perfil_para_membro(perfil, papel=PapelMembro.DONO)],
            )
            for membro in resolvidos:
                if membro.perfil_id != dono_perfil_id and membro.papel == PapelMembro.DONO:
                    membro.papel = PapelMembro.MEMBRO

        return resolvidos

    async def resolver_membro(self, membro: MembroSchema) -> MembroSchema:
        if membro.perfil_id:
            perfil = await self.buscar_perfil(perfil_id=membro.perfil_id)
            return self._mapper.perfil_para_membro(perfil, papel=membro.papel)

        if membro.email:
            perfil = await self._gateway.get_perfil_por_email(email=membro.email)
            if perfil is None:
                raise NotFoundError(f"Nao encontrei um perfil com o email {membro.email}.")
            return self._mapper.perfil_para_membro(perfil, papel=membro.papel)

        if membro.nome:
            return membro

        raise BadRequestError("Cada membro precisa ter perfil_id, email ou nome.")

    async def buscar_perfil(self, *, perfil_id: str) -> dict[str, Any]:
        perfil = await self._gateway.get_perfil(perfil_id=perfil_id)
        if perfil is None:
            raise NotFoundError("Perfil nao encontrado.")
        return perfil

    @classmethod
    def mesclar_membros(
        cls,
        atuais: list[MembroSchema],
        novos: list[MembroSchema],
    ) -> list[MembroSchema]:
        resultado = list(atuais)
        for novo in novos:
            chave_nova = cls.chave_membro(novo)
            existente = next(
                (m for m in resultado if cls.chave_membro(m) == chave_nova),
                None,
            )
            if existente is None:
                resultado.append(novo)
                continue
            existente.nome = novo.nome or existente.nome
            existente.email = novo.email or existente.email
            existente.perfil_id = novo.perfil_id or existente.perfil_id
            if novo.papel in {PapelMembro.DONO, PapelMembro.ADMINISTRADOR}:
                existente.papel = novo.papel
        return resultado

    @staticmethod
    def chave_membro(membro: MembroSchema) -> str:
        if membro.perfil_id:
            return f"perfil:{membro.perfil_id}"
        if membro.email:
            return f"email:{membro.email.lower()}"
        return f"nome:{(membro.nome or '').lower()}"

    @staticmethod
    def primeiro_perfil_id(membros: list[MembroSchema]) -> str | None:
        for membro in membros:
            if membro.perfil_id:
                return membro.perfil_id
        return None

    @staticmethod
    def marcar_dono(
        *,
        membros: list[MembroSchema],
        dono_perfil_id: str | None,
    ) -> None:
        if not dono_perfil_id:
            return
        for membro in membros:
            if membro.perfil_id == dono_perfil_id:
                membro.papel = PapelMembro.DONO
            elif membro.papel == PapelMembro.DONO:
                membro.papel = PapelMembro.MEMBRO

    @staticmethod
    def validar_espaco(
        *,
        tipo: TipoGrupo,
        membros: list[MembroSchema],
        dono_perfil_id: str | None,
    ) -> None:
        perfis = {m.perfil_id for m in membros if m.perfil_id}

        if not dono_perfil_id or dono_perfil_id not in perfis:
            raise BadRequestError("Grupo precisa ter um perfil dono cadastrado.")

        if tipo == TipoGrupo.INDIVIDUAL and len(perfis) != 1:
            raise BadRequestError("Espaco individual deve ter somente um perfil.")

        if tipo == TipoGrupo.CASAL and len(perfis) < 2:
            raise BadRequestError("Para criar um casal, informe dois perfis cadastrados.")

        if tipo == TipoGrupo.GRUPO and not perfis:
            raise BadRequestError("Grupo precisa ter ao menos um perfil cadastrado.")


class GrupoCrudService:
    def __init__(
        self,
        gateway: GruposGateway,
        reader: GrupoReader,
        resolver: GrupoMemberResolver,
        policy: GrupoPolicy,
        mapper: type[GrupoMapper] = GrupoMapper,
    ) -> None:
        self._gateway = gateway
        self._reader = reader
        self._resolver = resolver
        self._policy = policy
        self._mapper = mapper

    async def listar(self, *, perfil_id: str | None = None) -> GrupoListResponse:
        logger.info("grupos.listar.start perfil_id=%s", perfil_id)
        rows = await self._gateway.list_grupos(perfil_id=perfil_id)
        items = [self._mapper.mapear_grupo(r) for r in rows if isinstance(r, dict)]
        logger.info("grupos.listar.end perfil_id=%s total=%s", perfil_id, len(items))
        return GrupoListResponse(items=items, total=len(items))

    async def buscar(self, *, grupo_id: str) -> GrupoResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        return self._mapper.mapear_grupo(raw)

    async def buscar_por_codigo(self, *, codigo: str) -> GrupoResponse:
        raw = await self._reader.buscar_por_codigo_raw(codigo=codigo)
        return self._mapper.mapear_grupo(raw)

    async def criar(self, *, request: GrupoCreateRequest) -> GrupoResponse:
        logger.info(
            "grupos.criar.start nome=%s tipo=%s membros_input=%s dono_perfil_id=%s",
            request.nome,
            request.tipo.value,
            len(request.membros),
            request.dono_perfil_id,
        )
        membros = await self._resolver.resolver_membros(
            request.membros,
            dono_perfil_id=request.dono_perfil_id,
        )
        dono_perfil_id = request.dono_perfil_id or self._resolver.primeiro_perfil_id(membros)
        self._resolver.marcar_dono(membros=membros, dono_perfil_id=dono_perfil_id)
        self._resolver.validar_espaco(
            tipo=request.tipo,
            membros=membros,
            dono_perfil_id=dono_perfil_id,
        )

        payload: dict[str, Any] = {
            "nome": request.nome,
            "tipo": request.tipo.value,
            "descricao": request.descricao,
            "foto_url": request.foto_url,
            "dono_perfil_id": dono_perfil_id,
            "membros": self._mapper.dump_membros(membros),
        }
        if request.tipo != TipoGrupo.INDIVIDUAL:
            payload["codigo"] = await gerar_codigo_unico(self._gateway)

        criado = await self._gateway.insert_grupo(payload=payload)
        response = self._mapper.mapear_grupo(criado)
        logger.info(
            "grupos.criar.end grupo_id=%s codigo=%s tipo=%s membros=%s",
            response.id,
            response.codigo,
            response.tipo.value,
            len(response.membros),
        )
        return response

    async def atualizar(self, *, grupo_id: str, request: GrupoUpdateRequest) -> GrupoResponse:
        logger.info("grupos.atualizar.start grupo_id=%s fields=%s", grupo_id, sorted(request.model_fields_set))
        atual = await self._reader.buscar_raw(grupo_id=grupo_id)
        atual = await resolver_responsavel_legado(
            self._gateway,
            raw=atual,
            perfil_id=request.responsavel_perfil_id,
            mapper=self._mapper,
        )

        campos = set(request.model_fields_set) - {"responsavel_perfil_id"}
        if not campos:
            raise BadRequestError("Informe ao menos um campo para atualizar.")

        campos_editor = {"nome", "descricao", "foto_url"}
        campos_dono = {"tipo", "dono_perfil_id", "membros"}
        if campos & campos_editor:
            self._policy.exigir_editor(raw=atual, perfil_id=request.responsavel_perfil_id)
        if campos & campos_dono:
            self._policy.exigir_dono(raw=atual, perfil_id=request.responsavel_perfil_id)

        payload: dict[str, Any] = {}
        if "nome" in campos:
            payload["nome"] = request.nome
        if "tipo" in campos:
            payload["tipo"] = request.tipo.value if request.tipo else None
        if "descricao" in campos:
            payload["descricao"] = request.descricao
        if "foto_url" in campos:
            payload["foto_url"] = request.foto_url
            if request.foto_url != atual.get("foto_url"):
                await remover_foto_armazenada(self._gateway, atual.get("foto_caminho"))
                payload["foto_caminho"] = None
        if "dono_perfil_id" in campos:
            payload["dono_perfil_id"] = request.dono_perfil_id

        tipo_final = request.tipo or self._mapper.tipo_from_raw(atual.get("tipo"))
        dono_final = (
            request.dono_perfil_id
            if "dono_perfil_id" in campos
            else atual.get("dono_perfil_id")
        )

        if "membros" in campos:
            membros = await self._resolver.resolver_membros(
                request.membros or [],
                dono_perfil_id=dono_final,
            )
            self._resolver.marcar_dono(membros=membros, dono_perfil_id=dono_final)
            self._resolver.validar_espaco(
                tipo=tipo_final,
                membros=membros,
                dono_perfil_id=dono_final,
            )
            payload["membros"] = self._mapper.dump_membros(membros)
        elif "tipo" in campos or "dono_perfil_id" in campos:
            membros = self._mapper.parse_membros(atual.get("membros"))
            if dono_final and not any(m.perfil_id == dono_final for m in membros):
                membros = await self._resolver.resolver_membros(
                    membros,
                    dono_perfil_id=dono_final,
                )
            self._resolver.marcar_dono(membros=membros, dono_perfil_id=dono_final)
            self._resolver.validar_espaco(
                tipo=tipo_final,
                membros=membros,
                dono_perfil_id=dono_final,
            )
            payload["membros"] = self._mapper.dump_membros(membros)

        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")

        await self._gateway.update_grupo(grupo_id=grupo_id, payload=payload)
        response = await self.buscar(grupo_id=grupo_id)
        logger.info("grupos.atualizar.end grupo_id=%s", grupo_id)
        return response

    async def remover(self, *, grupo_id: str, responsavel_perfil_id: str | None) -> dict[str, Any]:
        logger.info("grupos.remover.start grupo_id=%s", grupo_id)
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_dono(raw=raw, perfil_id=responsavel_perfil_id)
        await remover_foto_armazenada(self._gateway, raw.get("foto_caminho"))
        await self._gateway.delete_grupo(grupo_id=grupo_id)
        logger.info("grupos.remover.end grupo_id=%s", grupo_id)
        return {"sucesso": True, "mensagem": "Grupo removido com sucesso."}


class GrupoMembershipService:
    def __init__(
        self,
        gateway: GruposGateway,
        reader: GrupoReader,
        resolver: GrupoMemberResolver,
        policy: GrupoPolicy,
        mapper: type[GrupoMapper] = GrupoMapper,
    ) -> None:
        self._gateway = gateway
        self._reader = reader
        self._resolver = resolver
        self._policy = policy
        self._mapper = mapper

    async def adicionar_membro(
        self,
        *,
        grupo_id: str,
        request: GrupoMembroRequest,
    ) -> GrupoResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=request.responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_dono(raw=raw, perfil_id=request.responsavel_perfil_id)
        if request.papel == PapelMembro.DONO:
            raise BadRequestError("Um grupo pode ter apenas um dono.")

        novo = await self._resolver.resolver_membros(
            [
                MembroSchema(
                    perfil_id=request.perfil_id,
                    email=request.email,
                    papel=request.papel,
                )
            ],
        )
        membros = self._mapper.parse_membros(raw.get("membros"))
        membros = self._resolver.mesclar_membros(membros, novo)

        tipo = self._mapper.tipo_from_raw(raw.get("tipo"))
        dono_perfil_id = raw.get("dono_perfil_id") or self._resolver.primeiro_perfil_id(membros)
        self._resolver.marcar_dono(membros=membros, dono_perfil_id=dono_perfil_id)
        self._resolver.validar_espaco(
            tipo=tipo,
            membros=membros,
            dono_perfil_id=dono_perfil_id,
        )

        await self._gateway.update_grupo(
            grupo_id=grupo_id,
            payload={
                "dono_perfil_id": dono_perfil_id,
                "membros": self._mapper.dump_membros(membros),
            },
        )
        return self._mapper.mapear_grupo(await self._reader.buscar_raw(grupo_id=grupo_id))

    async def remover_membro(
        self,
        *,
        grupo_id: str,
        perfil_id: str,
        responsavel_perfil_id: str | None,
    ) -> GrupoResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=responsavel_perfil_id,
            mapper=self._mapper,
        )
        dono_perfil_id = raw.get("dono_perfil_id")
        if perfil_id == dono_perfil_id:
            raise BadRequestError("O dono do grupo nao pode ser removido por aqui.")

        if responsavel_perfil_id != perfil_id:
            self._policy.exigir_dono(raw=raw, perfil_id=responsavel_perfil_id)

        membros = self._mapper.parse_membros(raw.get("membros"))
        novos_membros = [m for m in membros if m.perfil_id != perfil_id]
        if len(novos_membros) == len(membros):
            raise NotFoundError("Membro nao encontrado neste grupo.")

        tipo = self._mapper.tipo_from_raw(raw.get("tipo"))
        self._resolver.validar_espaco(
            tipo=tipo,
            membros=novos_membros,
            dono_perfil_id=dono_perfil_id,
        )
        await self._gateway.update_grupo(
            grupo_id=grupo_id,
            payload={
                "dono_perfil_id": dono_perfil_id,
                "membros": self._mapper.dump_membros(novos_membros),
            },
        )
        return self._mapper.mapear_grupo(await self._reader.buscar_raw(grupo_id=grupo_id))

    async def definir_papel_membro(
        self,
        *,
        grupo_id: str,
        perfil_id: str,
        request: PapelMembroUpdateRequest,
    ) -> GrupoResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=request.responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_dono(raw=raw, perfil_id=request.responsavel_perfil_id)
        if perfil_id == raw.get("dono_perfil_id"):
            raise BadRequestError("O papel do dono nao pode ser alterado por aqui.")

        membros = self._mapper.parse_membros(raw.get("membros"))
        alvo = next((m for m in membros if m.perfil_id == perfil_id), None)
        if alvo is None:
            raise NotFoundError("Membro nao encontrado neste grupo.")

        alvo.papel = request.papel
        self._resolver.marcar_dono(membros=membros, dono_perfil_id=raw.get("dono_perfil_id"))
        await self._gateway.update_grupo(
            grupo_id=grupo_id,
            payload={"membros": self._mapper.dump_membros(membros)},
        )
        return self._mapper.mapear_grupo(await self._reader.buscar_raw(grupo_id=grupo_id))


class GrupoInvitationService:
    def __init__(
        self,
        gateway: GruposGateway,
        reader: GrupoReader,
        policy: GrupoPolicy,
        *,
        web_app_base_url: str,
        web_group_invite_path: str,
        mapper: type[GrupoMapper] = GrupoMapper,
    ) -> None:
        self._gateway = gateway
        self._reader = reader
        self._policy = policy
        self._web_app_base_url = web_app_base_url
        self._web_group_invite_path = web_group_invite_path
        self._mapper = mapper

    async def gerar_convite(
        self,
        *,
        grupo_id: str,
        responsavel_perfil_id: str | None,
    ) -> GrupoConviteResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_membro(raw=raw, perfil_id=responsavel_perfil_id)

        if self._mapper.tipo_from_raw(raw.get("tipo")) == TipoGrupo.INDIVIDUAL:
            raise BadRequestError("Nao e possivel gerar convite para um espaco individual.")

        codigo = codigo_grupo(raw.get("codigo"))
        if codigo is None:
            codigo = await gerar_codigo_unico(self._gateway)
            await self._gateway.update_grupo(
                grupo_id=grupo_id,
                payload={"codigo": codigo},
            )

        url = montar_url_convite(
            base_url=self._web_app_base_url,
            invite_path=self._web_group_invite_path,
            codigo=codigo,
        )
        grupo_nome = str(raw.get("nome") or "Comidinhas")

        return GrupoConviteResponse(
            grupo_id=grupo_id,
            grupo_nome=grupo_nome,
            codigo=codigo,
            url=url,
            qr_code_payload=url,
            mensagem=montar_mensagem_convite(grupo_nome=grupo_nome, url=url, codigo=codigo),
        )


class GrupoJoinRequestsService:
    def __init__(
        self,
        gateway: GruposGateway,
        reader: GrupoReader,
        resolver: GrupoMemberResolver,
        policy: GrupoPolicy,
        mapper: type[GrupoMapper] = GrupoMapper,
    ) -> None:
        self._gateway = gateway
        self._reader = reader
        self._resolver = resolver
        self._policy = policy
        self._mapper = mapper

    async def solicitar_entrada(
        self,
        *,
        codigo: str,
        request: SolicitacaoEntradaGrupoRequest,
    ) -> SolicitacaoEntradaGrupoSchema:
        raw = await self._reader.buscar_por_codigo_raw(codigo=codigo)
        if self._mapper.tipo_from_raw(raw.get("tipo")) == TipoGrupo.INDIVIDUAL:
            raise BadRequestError("Nao e possivel solicitar entrada em um espaco individual.")

        perfil = await self._resolver.buscar_perfil(perfil_id=request.perfil_id)
        membros = self._mapper.parse_membros(raw.get("membros"))
        if any(m.perfil_id == request.perfil_id for m in membros):
            raise BadRequestError("Este perfil ja faz parte do grupo.")

        solicitacoes = self._mapper.parse_solicitacoes(raw.get("solicitacoes"))
        for solicitacao in reversed(solicitacoes):
            if solicitacao.perfil_id != request.perfil_id:
                continue
            if solicitacao.status == StatusSolicitacaoGrupo.PENDENTE:
                return solicitacao
            if solicitacao.status == StatusSolicitacaoGrupo.ACEITA:
                raise BadRequestError("Este perfil ja teve a entrada aceita neste grupo.")

        solicitacao = SolicitacaoEntradaGrupoSchema(
            id=uuid4().hex,
            perfil_id=request.perfil_id,
            nome=perfil.get("nome"),
            email=perfil.get("email"),
            mensagem=request.mensagem,
            status=StatusSolicitacaoGrupo.PENDENTE,
            solicitado_em=agora(),
        )
        solicitacoes.append(solicitacao)
        await self._gateway.update_grupo(
            grupo_id=str(raw.get("id", "")),
            payload={"solicitacoes": self._mapper.dump_solicitacoes(solicitacoes)},
        )
        return solicitacao

    async def listar_solicitacoes(
        self,
        *,
        grupo_id: str,
        responsavel_perfil_id: str | None,
        status: StatusSolicitacaoGrupo | None = None,
    ) -> SolicitacaoEntradaGrupoListResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_dono(raw=raw, perfil_id=responsavel_perfil_id)
        solicitacoes = self._mapper.parse_solicitacoes(raw.get("solicitacoes"))
        if status is not None:
            solicitacoes = [s for s in solicitacoes if s.status == status]
        return SolicitacaoEntradaGrupoListResponse(
            items=solicitacoes,
            total=len(solicitacoes),
        )

    async def aceitar_solicitacao(
        self,
        *,
        grupo_id: str,
        solicitacao_id: str,
        request: ResponderSolicitacaoGrupoRequest,
    ) -> GrupoResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=request.responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_dono(raw=raw, perfil_id=request.responsavel_perfil_id)

        solicitacoes = self._mapper.parse_solicitacoes(raw.get("solicitacoes"))
        solicitacao = encontrar_solicitacao_pendente(
            solicitacoes=solicitacoes,
            solicitacao_id=solicitacao_id,
        )

        perfil = await self._resolver.buscar_perfil(perfil_id=solicitacao.perfil_id)
        membros = self._mapper.parse_membros(raw.get("membros"))
        membros = self._resolver.mesclar_membros(
            membros,
            [self._mapper.perfil_para_membro(perfil, papel=PapelMembro.MEMBRO)],
        )
        self._resolver.marcar_dono(membros=membros, dono_perfil_id=raw.get("dono_perfil_id"))

        solicitacao.status = StatusSolicitacaoGrupo.ACEITA
        solicitacao.respondido_em = agora()
        solicitacao.respondido_por_perfil_id = request.responsavel_perfil_id

        await self._gateway.update_grupo(
            grupo_id=grupo_id,
            payload={
                "membros": self._mapper.dump_membros(membros),
                "solicitacoes": self._mapper.dump_solicitacoes(solicitacoes),
            },
        )
        return self._mapper.mapear_grupo(await self._reader.buscar_raw(grupo_id=grupo_id))

    async def recusar_solicitacao(
        self,
        *,
        grupo_id: str,
        solicitacao_id: str,
        request: ResponderSolicitacaoGrupoRequest,
    ) -> GrupoResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=request.responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_dono(raw=raw, perfil_id=request.responsavel_perfil_id)

        solicitacoes = self._mapper.parse_solicitacoes(raw.get("solicitacoes"))
        solicitacao = encontrar_solicitacao_pendente(
            solicitacoes=solicitacoes,
            solicitacao_id=solicitacao_id,
        )
        solicitacao.status = StatusSolicitacaoGrupo.RECUSADA
        solicitacao.respondido_em = agora()
        solicitacao.respondido_por_perfil_id = request.responsavel_perfil_id

        await self._gateway.update_grupo(
            grupo_id=grupo_id,
            payload={"solicitacoes": self._mapper.dump_solicitacoes(solicitacoes)},
        )
        return self._mapper.mapear_grupo(await self._reader.buscar_raw(grupo_id=grupo_id))


class GrupoPhotoService:
    def __init__(
        self,
        gateway: GruposGateway,
        reader: GrupoReader,
        policy: GrupoPolicy,
        mapper: type[GrupoMapper] = GrupoMapper,
    ) -> None:
        self._gateway = gateway
        self._reader = reader
        self._policy = policy
        self._mapper = mapper

    async def upload_foto(
        self,
        *,
        grupo_id: str,
        responsavel_perfil_id: str | None,
        file: UploadFile,
    ) -> GrupoResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_editor(raw=raw, perfil_id=responsavel_perfil_id)

        content_type = file.content_type or ""
        ext = _TIPOS_IMAGEM.get(content_type)
        if ext is None:
            raise BadRequestError("Envie uma imagem JPG, PNG, WEBP ou GIF.")

        conteudo = await file.read()
        if not conteudo:
            raise BadRequestError("Arquivo vazio.")
        if len(conteudo) > self._gateway.max_group_photo_bytes:
            raise BadRequestError(
                f"Foto excede o limite de {self._gateway.max_group_photo_bytes // (1024 * 1024)}MB."
            )

        await remover_foto_armazenada(self._gateway, raw.get("foto_caminho"))
        caminho = f"{grupo_id}/{uuid4().hex}.{ext}"
        upload = await self._gateway.upload_group_foto(
            object_path=caminho,
            content=conteudo,
            filename=file.filename or f"foto.{ext}",
            content_type=content_type,
        )
        await self._gateway.update_grupo(
            grupo_id=grupo_id,
            payload={"foto_url": upload["public_url"], "foto_caminho": upload["path"]},
        )
        return self._mapper.mapear_grupo(await self._reader.buscar_raw(grupo_id=grupo_id))

    async def remover_foto(
        self,
        *,
        grupo_id: str,
        responsavel_perfil_id: str | None,
    ) -> GrupoResponse:
        raw = await self._reader.buscar_raw(grupo_id=grupo_id)
        raw = await resolver_responsavel_legado(
            self._gateway,
            raw=raw,
            perfil_id=responsavel_perfil_id,
            mapper=self._mapper,
        )
        self._policy.exigir_editor(raw=raw, perfil_id=responsavel_perfil_id)
        await remover_foto_armazenada(self._gateway, raw.get("foto_caminho"))
        await self._gateway.update_grupo(
            grupo_id=grupo_id,
            payload={"foto_url": None, "foto_caminho": None},
        )
        return self._mapper.mapear_grupo(await self._reader.buscar_raw(grupo_id=grupo_id))


async def remover_foto_armazenada(gateway: GruposGateway, object_path: Any) -> None:
    if not isinstance(object_path, str) or not object_path:
        return
    await gateway.remove_group_foto(object_path=object_path)


async def resolver_responsavel_legado(
    gateway: GruposGateway,
    *,
    raw: dict[str, Any],
    perfil_id: str | None,
    mapper: type[GrupoMapper] = GrupoMapper,
) -> dict[str, Any]:
    if not perfil_id:
        return raw

    membros = mapper.parse_membros(raw.get("membros"))
    if raw.get("dono_perfil_id") == perfil_id or any(m.perfil_id == perfil_id for m in membros):
        return raw

    perfil = await gateway.get_perfil(perfil_id=perfil_id)
    if not isinstance(perfil, dict):
        return raw

    perfil_email = normalizar_email(perfil.get("email"))
    if not perfil_email:
        return raw

    membro = next((m for m in membros if normalizar_email(m.email) == perfil_email), None)
    if membro is None:
        return raw

    mudou = False
    if membro.perfil_id != perfil_id:
        membro.perfil_id = perfil_id
        mudou = True
    if not membro.nome and perfil.get("nome"):
        membro.nome = str(perfil.get("nome"))
        mudou = True
    if not membro.email and perfil.get("email"):
        membro.email = str(perfil.get("email"))
        mudou = True

    if not raw.get("dono_perfil_id"):
        raw["dono_perfil_id"] = perfil_id
        membro.papel = PapelMembro.DONO
        mudou = True

    if raw.get("dono_perfil_id") == perfil_id:
        for item in membros:
            proximo_papel = PapelMembro.DONO if item is membro else (
                PapelMembro.MEMBRO if item.papel == PapelMembro.DONO else item.papel
            )
            if item.papel != proximo_papel:
                item.papel = proximo_papel
                mudou = True

    if not mudou:
        return raw

    raw["membros"] = mapper.dump_membros(membros)
    payload: dict[str, Any] = {"membros": raw["membros"]}
    if raw.get("dono_perfil_id") == perfil_id:
        payload["dono_perfil_id"] = perfil_id

    grupo_id = str(raw.get("id") or "")
    if grupo_id:
        await gateway.update_grupo(grupo_id=grupo_id, payload=payload)

    return raw


def normalizar_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    return email or None


async def gerar_codigo_unico(gateway: GruposGateway) -> str:
    for _ in range(20):
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        existente = await gateway.get_grupo_por_codigo(codigo=codigo)
        if existente is None:
            return codigo
    raise ConflictError("Nao foi possivel gerar um codigo unico para o grupo.")


def codigo_grupo(raw_codigo: Any) -> str | None:
    if not isinstance(raw_codigo, str):
        return None
    codigo = raw_codigo.strip()
    if len(codigo) == 6 and codigo.isdigit():
        return codigo
    return None


def montar_url_convite(*, base_url: str, invite_path: str, codigo: str) -> str:
    base = (base_url or "https://comidinhas-web-production.up.railway.app").strip()
    path = (invite_path or "/entrar").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    url = urljoin(f"{base.rstrip('/')}/", path.lstrip("/"))
    return f"{url}?{urlencode({'codigo': codigo})}"


def montar_mensagem_convite(*, grupo_nome: str, url: str, codigo: str) -> str:
    return (
        f"Bora entrar no meu grupo {grupo_nome} no Comidinhas?\n\n"
        f"Acesse: {url}\n"
        f"Codigo do grupo: {codigo}"
    )


def encontrar_solicitacao_pendente(
    *,
    solicitacoes: list[SolicitacaoEntradaGrupoSchema],
    solicitacao_id: str,
) -> SolicitacaoEntradaGrupoSchema:
    solicitacao = next((s for s in solicitacoes if s.id == solicitacao_id), None)
    if solicitacao is None:
        raise NotFoundError("Solicitacao nao encontrada neste grupo.")
    if solicitacao.status != StatusSolicitacaoGrupo.PENDENTE:
        raise BadRequestError("Esta solicitacao ja foi respondida.")
    return solicitacao


def agora() -> datetime:
    return datetime.now(timezone.utc)
