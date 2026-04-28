from __future__ import annotations

from fastapi import UploadFile

from app.modules.grupos.policies import GrupoPolicy
from app.modules.grupos.repositories import GruposGateway
from app.modules.grupos.schemas import (
    GrupoCreateRequest,
    GrupoListResponse,
    GrupoMembroRequest,
    GrupoResponse,
    GrupoUpdateRequest,
    PapelMembroUpdateRequest,
    ResponderSolicitacaoGrupoRequest,
    SolicitacaoEntradaGrupoListResponse,
    SolicitacaoEntradaGrupoRequest,
    SolicitacaoEntradaGrupoSchema,
    StatusSolicitacaoGrupo,
)
from app.modules.grupos.services import (
    GrupoCrudService,
    GrupoJoinRequestsService,
    GrupoMemberResolver,
    GrupoMembershipService,
    GrupoPhotoService,
    GrupoReader,
)


class ManageGruposUseCase:
    """Facade that preserves the route contract while delegating focused work."""

    def __init__(self, client: GruposGateway) -> None:
        reader = GrupoReader(client)
        resolver = GrupoMemberResolver(client)
        policy = GrupoPolicy()
        self._crud = GrupoCrudService(client, reader, resolver, policy)
        self._members = GrupoMembershipService(client, reader, resolver, policy)
        self._requests = GrupoJoinRequestsService(client, reader, resolver, policy)
        self._photos = GrupoPhotoService(client, reader, policy)

    async def listar(self, *, perfil_id: str | None = None) -> GrupoListResponse:
        return await self._crud.listar(perfil_id=perfil_id)

    async def buscar(self, *, grupo_id: str) -> GrupoResponse:
        return await self._crud.buscar(grupo_id=grupo_id)

    async def buscar_por_codigo(self, *, codigo: str) -> GrupoResponse:
        return await self._crud.buscar_por_codigo(codigo=codigo)

    async def criar(self, *, request: GrupoCreateRequest) -> GrupoResponse:
        return await self._crud.criar(request=request)

    async def atualizar(self, *, grupo_id: str, request: GrupoUpdateRequest) -> GrupoResponse:
        return await self._crud.atualizar(grupo_id=grupo_id, request=request)

    async def remover(self, *, grupo_id: str, responsavel_perfil_id: str | None) -> dict:
        return await self._crud.remover(
            grupo_id=grupo_id,
            responsavel_perfil_id=responsavel_perfil_id,
        )

    async def adicionar_membro(
        self,
        *,
        grupo_id: str,
        request: GrupoMembroRequest,
    ) -> GrupoResponse:
        return await self._members.adicionar_membro(grupo_id=grupo_id, request=request)

    async def remover_membro(
        self,
        *,
        grupo_id: str,
        perfil_id: str,
        responsavel_perfil_id: str | None,
    ) -> GrupoResponse:
        return await self._members.remover_membro(
            grupo_id=grupo_id,
            perfil_id=perfil_id,
            responsavel_perfil_id=responsavel_perfil_id,
        )

    async def definir_papel_membro(
        self,
        *,
        grupo_id: str,
        perfil_id: str,
        request: PapelMembroUpdateRequest,
    ) -> GrupoResponse:
        return await self._members.definir_papel_membro(
            grupo_id=grupo_id,
            perfil_id=perfil_id,
            request=request,
        )

    async def solicitar_entrada(
        self,
        *,
        codigo: str,
        request: SolicitacaoEntradaGrupoRequest,
    ) -> SolicitacaoEntradaGrupoSchema:
        return await self._requests.solicitar_entrada(codigo=codigo, request=request)

    async def listar_solicitacoes(
        self,
        *,
        grupo_id: str,
        responsavel_perfil_id: str | None,
        status: StatusSolicitacaoGrupo | None = None,
    ) -> SolicitacaoEntradaGrupoListResponse:
        return await self._requests.listar_solicitacoes(
            grupo_id=grupo_id,
            responsavel_perfil_id=responsavel_perfil_id,
            status=status,
        )

    async def aceitar_solicitacao(
        self,
        *,
        grupo_id: str,
        solicitacao_id: str,
        request: ResponderSolicitacaoGrupoRequest,
    ) -> GrupoResponse:
        return await self._requests.aceitar_solicitacao(
            grupo_id=grupo_id,
            solicitacao_id=solicitacao_id,
            request=request,
        )

    async def recusar_solicitacao(
        self,
        *,
        grupo_id: str,
        solicitacao_id: str,
        request: ResponderSolicitacaoGrupoRequest,
    ) -> GrupoResponse:
        return await self._requests.recusar_solicitacao(
            grupo_id=grupo_id,
            solicitacao_id=solicitacao_id,
            request=request,
        )

    async def upload_foto(
        self,
        *,
        grupo_id: str,
        responsavel_perfil_id: str | None,
        file: UploadFile,
    ) -> GrupoResponse:
        return await self._photos.upload_foto(
            grupo_id=grupo_id,
            responsavel_perfil_id=responsavel_perfil_id,
            file=file,
        )

    async def remover_foto(
        self,
        *,
        grupo_id: str,
        responsavel_perfil_id: str | None,
    ) -> GrupoResponse:
        return await self._photos.remover_foto(
            grupo_id=grupo_id,
            responsavel_perfil_id=responsavel_perfil_id,
        )
