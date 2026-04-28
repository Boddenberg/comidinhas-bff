from __future__ import annotations

from typing import Any

from app.core.errors import PermissionDeniedError
from app.modules.grupos.mappers import GrupoMapper
from app.modules.grupos.schemas import PapelMembro


class GrupoPolicy:
    def __init__(self, mapper: type[GrupoMapper] = GrupoMapper) -> None:
        self._mapper = mapper

    def exigir_dono(self, *, raw: dict[str, Any], perfil_id: str | None) -> None:
        if self.papel_no_grupo(raw=raw, perfil_id=perfil_id) == PapelMembro.DONO:
            return
        raise PermissionDeniedError("Apenas o dono do grupo pode fazer esta acao.")

    def exigir_editor(self, *, raw: dict[str, Any], perfil_id: str | None) -> None:
        if self.papel_no_grupo(raw=raw, perfil_id=perfil_id) in {
            PapelMembro.DONO,
            PapelMembro.ADMINISTRADOR,
        }:
            return
        raise PermissionDeniedError("Apenas o dono ou administrador do grupo pode fazer esta acao.")

    def papel_no_grupo(
        self,
        *,
        raw: dict[str, Any],
        perfil_id: str | None,
    ) -> PapelMembro | None:
        if not perfil_id:
            return None
        if raw.get("dono_perfil_id") == perfil_id:
            return PapelMembro.DONO
        for membro in self._mapper.parse_membros(raw.get("membros")):
            if membro.perfil_id == perfil_id:
                return membro.papel
        return None
