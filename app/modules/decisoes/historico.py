"""Shared helpers around the AI suggestion history.

The same `sugestoes_ia_historico` table backs three different flows:

- `decidir_restaurante` (a "surprise me" call that returns one place)
- `recomendar_restaurantes` (free-text recommendation, multiple options)
- `today_recommendations` (the Home "today" widget)

We centralise the loader, the windowing rules and the persistence so the
three use cases stay focused on their own pipeline.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# Janela de exclusao dura: nunca repete o mesmo lugar dentro deste prazo.
WINDOW_DAY_HOURS = 24
# Janela "macia": evita repetir dentro da semana, mas pode cair se nao houver
# alternativas suficientes.
WINDOW_WEEK_DAYS = 7
# Janela usada para extrair sinais de personalizacao (cozinhas/moods recentes).
WINDOW_PERSONALIZATION_DAYS = 30


@dataclass(frozen=True)
class HistoricoSugestao:
    """Representacao tipada de uma linha do `sugestoes_ia_historico`."""

    lugar_id: str | None
    google_place_id: str | None
    nome: str | None
    fonte: str | None
    posicao: int
    criterios: dict[str, Any]
    motivo: str | None
    criado_em: datetime | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "HistoricoSugestao":
        return cls(
            lugar_id=_as_str(row.get("lugar_id")),
            google_place_id=_as_str(row.get("google_place_id")),
            nome=_as_str(row.get("nome")),
            fonte=_as_str(row.get("fonte")),
            posicao=_as_int(row.get("posicao"), default=1),
            criterios=row.get("criterios") if isinstance(row.get("criterios"), dict) else {},
            motivo=_as_str(row.get("motivo")),
            criado_em=_parse_iso(row.get("criado_em")),
        )


@dataclass
class HistoricoContexto:
    """Resultado de carregar o historico para um grupo."""

    sugestoes: list[HistoricoSugestao] = field(default_factory=list)
    agora: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def lugares_evitar_dia(self) -> set[str]:
        return self._coletar_ids(horas=WINDOW_DAY_HOURS, somente_principais=False)

    def google_evitar_dia(self) -> set[str]:
        return self._coletar_google(horas=WINDOW_DAY_HOURS, somente_principais=False)

    def lugares_evitar_semana(self) -> set[str]:
        return self._coletar_ids(
            horas=WINDOW_WEEK_DAYS * 24, somente_principais=True
        )

    def google_evitar_semana(self) -> set[str]:
        return self._coletar_google(
            horas=WINDOW_WEEK_DAYS * 24, somente_principais=True
        )

    def resumo_personalizacao(
        self, *, max_itens: int = 5
    ) -> dict[str, list[str] | int]:
        """Sinais leves para o prompt: cozinhas/moods/dias mais recentes.

        Mantemos so a contagem para o LLM - sem PII, sem texto longo - so o
        suficiente para que ele entenda o contexto e fale algo pessoal.
        """
        cozinhas: Counter[str] = Counter()
        moods: Counter[str] = Counter()
        dias: Counter[str] = Counter()
        ultimos_nomes: list[str] = []
        limite = self.agora - timedelta(days=WINDOW_PERSONALIZATION_DAYS)
        for sug in self.sugestoes:
            if sug.criado_em is None or sug.criado_em < limite:
                continue
            if sug.nome and sug.nome not in ultimos_nomes:
                ultimos_nomes.append(sug.nome)
            criterios = sug.criterios or {}
            for c in _as_list(criterios.get("cozinhas")):
                cozinhas[c.lower()] += 1
            mood = _as_str(criterios.get("mood"))
            if mood:
                moods[mood.lower()] += 1
            dia = _as_str(criterios.get("dia_semana"))
            if dia:
                dias[dia.lower()] += 1
        return {
            "total_sugestoes_30d": sum(1 for s in self.sugestoes if s.criado_em and s.criado_em >= limite),
            "cozinhas_frequentes": [item for item, _ in cozinhas.most_common(max_itens)],
            "moods_frequentes": [item for item, _ in moods.most_common(max_itens)],
            "ultimos_nomes": ultimos_nomes[:max_itens],
        }

    def _coletar_ids(self, *, horas: int, somente_principais: bool) -> set[str]:
        limite = self.agora - timedelta(hours=horas)
        out: set[str] = set()
        for sug in self.sugestoes:
            if sug.criado_em is None or sug.criado_em < limite:
                continue
            if somente_principais and sug.posicao != 1:
                continue
            if sug.lugar_id:
                out.add(sug.lugar_id)
        return out

    def _coletar_google(self, *, horas: int, somente_principais: bool) -> set[str]:
        limite = self.agora - timedelta(hours=horas)
        out: set[str] = set()
        for sug in self.sugestoes:
            if sug.criado_em is None or sug.criado_em < limite:
                continue
            if somente_principais and sug.posicao != 1:
                continue
            if sug.google_place_id:
                out.add(sug.google_place_id)
        return out


async def carregar_contexto(
    *,
    supabase_client: Any,
    grupo_id: str,
) -> HistoricoContexto:
    """Le o historico recente do grupo. Falhas viram contexto vazio.

    O recurso e best-effort: se a leitura falhar (tabela ausente em ambiente
    de desenvolvimento, problema de rede, etc.), seguimos sem historico em
    vez de bloquear o usuario.
    """
    agora = datetime.now(timezone.utc)
    since = agora - timedelta(days=WINDOW_PERSONALIZATION_DAYS)
    try:
        rows = await supabase_client.list_sugestoes_ia_recentes(
            grupo_id=grupo_id,
            since_iso=since.isoformat(timespec="seconds"),
            limit=200,
        )
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning(
            "decisoes.historico.load_failed grupo_id=%s error=%s", grupo_id, exc
        )
        return HistoricoContexto(sugestoes=[], agora=agora)

    sugestoes = [HistoricoSugestao.from_row(row) for row in rows if isinstance(row, dict)]
    return HistoricoContexto(sugestoes=sugestoes, agora=agora)


async def registrar_sugestoes(
    *,
    supabase_client: Any,
    grupo_id: str,
    perfil_id: str | None,
    fonte: str,
    modelo: str | None,
    criterios: dict[str, Any] | None,
    sugestoes: Iterable[dict[str, Any]],
) -> None:
    """Persiste a escolha + alternativas. Falhas sao logadas e ignoradas."""
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(sugestoes, start=1):
        nome = _as_str(item.get("nome"))
        lugar_id = _as_str(item.get("lugar_id"))
        google_place_id = _as_str(item.get("google_place_id"))
        if not nome or (not lugar_id and not google_place_id):
            continue
        origem = _as_str(item.get("origem")) or (
            "comidinhas" if lugar_id else "google"
        )
        row: dict[str, Any] = {
            "grupo_id": grupo_id,
            "perfil_id": perfil_id,
            "lugar_id": lugar_id,
            "google_place_id": google_place_id,
            "nome": nome[:200],
            "origem": origem,
            "fonte": fonte,
            "posicao": index,
            "criterios": criterios or {},
        }
        motivo = _as_str(item.get("motivo"))
        if motivo:
            row["motivo"] = motivo[:1200]
        if modelo:
            row["modelo"] = modelo[:80]
        rows.append(row)

    if not rows:
        return

    try:
        await supabase_client.insert_sugestoes_ia(rows=rows)
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning(
            "decisoes.historico.persist_failed grupo_id=%s fonte=%s error=%s",
            grupo_id,
            fonte,
            exc,
        )


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _as_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
