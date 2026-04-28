from __future__ import annotations

from typing import Any

from app.modules.grupos.schemas import (
    GrupoResponse,
    MembroSchema,
    PapelMembro,
    SolicitacaoEntradaGrupoSchema,
    StatusSolicitacaoGrupo,
    TipoGrupo,
)


class GrupoMapper:
    @classmethod
    def mapear_grupo(cls, raw: dict[str, Any]) -> GrupoResponse:
        return GrupoResponse(
            id=str(raw.get("id", "")),
            codigo=raw.get("codigo"),
            nome=str(raw.get("nome", "")),
            tipo=cls.tipo_from_raw(raw.get("tipo")),
            descricao=raw.get("descricao"),
            foto_url=raw.get("foto_url"),
            dono_perfil_id=raw.get("dono_perfil_id"),
            membros=cls.parse_membros(raw.get("membros")),
            solicitacoes=cls.parse_solicitacoes(raw.get("solicitacoes")),
            criado_em=raw.get("criado_em"),
            atualizado_em=raw.get("atualizado_em"),
        )

    @classmethod
    def parse_membros(cls, raw: Any) -> list[MembroSchema]:
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
                        papel=cls.papel_from_raw(item.get("papel")),
                    )
                )
            except Exception:
                continue
        return membros

    @classmethod
    def parse_solicitacoes(cls, raw: Any) -> list[SolicitacaoEntradaGrupoSchema]:
        if not isinstance(raw, list):
            return []

        solicitacoes: list[SolicitacaoEntradaGrupoSchema] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                solicitacoes.append(
                    SolicitacaoEntradaGrupoSchema(
                        id=str(item.get("id", "")),
                        perfil_id=str(item.get("perfil_id", "")),
                        nome=item.get("nome"),
                        email=item.get("email"),
                        mensagem=item.get("mensagem"),
                        status=cls.status_solicitacao_from_raw(item.get("status")),
                        solicitado_em=item.get("solicitado_em"),
                        respondido_em=item.get("respondido_em"),
                        respondido_por_perfil_id=item.get("respondido_por_perfil_id"),
                    )
                )
            except Exception:
                continue
        return solicitacoes

    @staticmethod
    def dump_membros(membros: list[MembroSchema]) -> list[dict[str, Any]]:
        return [m.model_dump(mode="json", exclude_none=True) for m in membros]

    @staticmethod
    def dump_solicitacoes(
        solicitacoes: list[SolicitacaoEntradaGrupoSchema],
    ) -> list[dict[str, Any]]:
        return [s.model_dump(mode="json", exclude_none=True) for s in solicitacoes]

    @staticmethod
    def perfil_para_membro(perfil: dict[str, Any], *, papel: PapelMembro) -> MembroSchema:
        return MembroSchema(
            perfil_id=str(perfil.get("id", "")),
            nome=perfil.get("nome"),
            email=perfil.get("email"),
            papel=papel,
        )

    @staticmethod
    def tipo_from_raw(raw: Any) -> TipoGrupo:
        try:
            return TipoGrupo(raw or TipoGrupo.CASAL.value)
        except ValueError:
            return TipoGrupo.GRUPO

    @staticmethod
    def papel_from_raw(raw: Any) -> PapelMembro:
        try:
            return PapelMembro(raw or PapelMembro.MEMBRO.value)
        except ValueError:
            return PapelMembro.MEMBRO

    @staticmethod
    def status_solicitacao_from_raw(raw: Any) -> StatusSolicitacaoGrupo:
        try:
            return StatusSolicitacaoGrupo(raw or StatusSolicitacaoGrupo.PENDENTE.value)
        except ValueError:
            return StatusSolicitacaoGrupo.PENDENTE
