from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Any

from app.modules.guias_ai.schemas import (
    EnrichedItem,
    GuiaIaSugestaoCard,
    GuiaIaSugestoes,
    StatusMatching,
)

logger = logging.getLogger(__name__)


class SuggestionEngine:
    """Compute privacy-preserving "where to go first" cards for a guide.

    The Comidinhas data model only stores the member's `cidade` (no street-level
    address). We therefore compute aggregate, non-revealing suggestions:

    - "Mais facil para todos" prefers restaurants in the most common city among
      the group's members (so nobody is far) without naming individuals.
    - All cards expose only restaurant-side data; never member identifiers,
      addresses or coordinates.
    """

    def calcular(
        self,
        *,
        items: list[EnrichedItem],
        membros: list[dict[str, Any]],
        inventario_grupo: list[dict[str, Any]] | None = None,
    ) -> GuiaIaSugestoes:
        if not items:
            return GuiaIaSugestoes(
                aviso_privacidade=(
                    "Sugestoes calculadas apenas com dados publicos dos restaurantes."
                ),
            )

        membros_validos = [m for m in membros if isinstance(m, dict)]
        cidades_grupo = _coletar_cidades(membros_validos)
        cidade_predominante = (
            cidades_grupo.most_common(1)[0][0] if cidades_grupo else None
        )

        candidatos = [
            item
            for item in items
            if item.status_matching
            not in (StatusMatching.IGNORADO, StatusMatching.NAO_ENCONTRADO)
        ]
        if not candidatos:
            candidatos = items

        centroide = _centroide_grupo(inventario_grupo or [])

        melhor_para_hoje = self._melhor_para_hoje(candidatos)
        mais_facil = self._mais_facil(candidatos, cidade_predominante, centroide)
        melhor_avaliado = self._melhor_avaliado(candidatos)
        mais_desejado = self._mais_desejado(candidatos)
        novidade = self._novidade(candidatos)

        aviso = self._montar_aviso(
            membros_validos,
            cidades_grupo,
            cidade_predominante,
            centroide_disponivel=centroide is not None,
        )

        return GuiaIaSugestoes(
            melhor_para_hoje=melhor_para_hoje,
            mais_facil_para_todos=mais_facil,
            melhor_avaliado=melhor_avaliado,
            mais_desejado_pelo_grupo=mais_desejado,
            novidade_para_o_grupo=novidade,
            aviso_privacidade=aviso,
        )

    def _melhor_para_hoje(self, items: list[EnrichedItem]) -> GuiaIaSugestaoCard | None:
        scored: list[tuple[float, EnrichedItem]] = []
        for item in items:
            if item.aberto_agora is False:
                continue
            base = (item.rating or 0.0) * 2.0
            base += (item.total_avaliacoes or 0) / 1500.0
            base += 0.5 if item.aberto_agora else 0.0
            base += _confidence_bonus(item)
            base -= _bad_status_penalty(item)
            scored.append((base, item))
        return _to_card(
            scored,
            id_prefix="melhor_para_hoje",
            titulo="Melhor para hoje",
            motivo_template=(
                "Esta aberto agora, tem boas avaliacoes e dados consistentes."
            ),
        )

    def _mais_facil(
        self,
        items: list[EnrichedItem],
        cidade_predominante: str | None,
        centroide: tuple[float, float] | None,
    ) -> GuiaIaSugestaoCard | None:
        # Escala de distancia em km: km_max afasta restaurantes muito distantes do
        # "centro de gravidade" do que o grupo ja salvou.
        scored: list[tuple[float, EnrichedItem]] = []
        for item in items:
            score = (item.rating or 0.0)
            score += _confidence_bonus(item)
            cidade_item = (item.cidade_normalizada or item.extracted.cidade or "").strip().lower()
            if cidade_predominante and cidade_item == cidade_predominante.lower():
                score += 1.5
            elif cidade_predominante:
                score -= 0.5

            if centroide and item.latitude is not None and item.longitude is not None:
                dist_km = _haversine_km(
                    centroide[0],
                    centroide[1],
                    item.latitude,
                    item.longitude,
                )
                # Quanto mais perto, mais bonus. Cap em 30km para nao virar dominante.
                proximity = max(0.0, 1.0 - min(dist_km, 30.0) / 30.0)
                score += proximity * 2.0
            score -= _bad_status_penalty(item)
            scored.append((score, item))
        if not scored:
            return None
        if centroide:
            motivo = (
                "Bem localizado em relacao aos lugares que voces ja salvaram, "
                "com dados confiaveis."
            )
        elif cidade_predominante:
            motivo = "Tempo medio de deslocamento baixo para o grupo e dados confiaveis."
        else:
            motivo = "Bem localizado e com bons dados publicos."
        return _to_card(
            scored,
            id_prefix="mais_facil",
            titulo="Mais facil para todos",
            motivo_template=motivo,
        )

    def _melhor_avaliado(self, items: list[EnrichedItem]) -> GuiaIaSugestaoCard | None:
        scored = [
            (
                (item.rating or 0.0) * 4
                + min((item.total_avaliacoes or 0) / 500.0, 5.0)
                - _bad_status_penalty(item),
                item,
            )
            for item in items
            if item.rating is not None
        ]
        return _to_card(
            scored,
            id_prefix="melhor_avaliado",
            titulo="Melhor avaliado",
            motivo_template="Maior nota agregada com volume relevante de avaliacoes.",
        )

    def _mais_desejado(self, items: list[EnrichedItem]) -> GuiaIaSugestaoCard | None:
        scored: list[tuple[float, EnrichedItem]] = []
        for item in items:
            lugar = item.lugar_existente or {}
            status_lugar = (lugar.get("status") or "").lower() if isinstance(lugar, dict) else ""
            favorito = bool(lugar.get("favorito")) if isinstance(lugar, dict) else False
            score = 0.0
            if status_lugar == "quero_ir":
                score += 3.0
            if favorito:
                score += 2.5
            if status_lugar == "quero_voltar":
                score += 1.5
            score += (item.rating or 0.0) * 0.4
            if score <= 0:
                continue
            scored.append((score, item))
        return _to_card(
            scored,
            id_prefix="mais_desejado",
            titulo="Mais desejado pelo grupo",
            motivo_template="Aparece como favorito ou 'quero ir' para o grupo.",
        )

    def _novidade(self, items: list[EnrichedItem]) -> GuiaIaSugestaoCard | None:
        scored: list[tuple[float, EnrichedItem]] = []
        for item in items:
            if item.lugar_existente:
                continue
            if item.status_matching in (
                StatusMatching.IGNORADO,
                StatusMatching.NAO_ENCONTRADO,
            ):
                continue
            score = (item.rating or 3.5) * 1.5
            score += _confidence_bonus(item)
            score -= _bad_status_penalty(item)
            scored.append((score, item))
        return _to_card(
            scored,
            id_prefix="novidade",
            titulo="Novidade para o grupo",
            motivo_template="Restaurante que ainda nao esta nos lugares salvos do grupo.",
        )

    def _montar_aviso(
        self,
        membros: list[dict[str, Any]],
        cidades_grupo: Counter[str],
        cidade_predominante: str | None,
        *,
        centroide_disponivel: bool,
    ) -> str:
        if centroide_disponivel:
            return (
                "Calculo agregado a partir dos lugares ja salvos pelo grupo "
                "e da cidade dos membros, sem expor enderecos individuais."
            )
        if not membros:
            return (
                "Sem dados do grupo: sugestoes baseadas apenas em dados publicos dos restaurantes."
            )
        if not cidades_grupo:
            return (
                "O grupo ainda nao tem cidade salva nos perfis. "
                "Sugestoes calculadas sem informacao de localizacao do grupo."
            )
        if cidade_predominante and len(cidades_grupo) == 1:
            return (
                "Calculo agregado considerando a cidade salva pelos membros, "
                "sem revelar enderecos individuais."
            )
        return (
            "Calculo agregado considerando as cidades dos membros disponiveis, "
            "sem expor enderecos individuais."
        )


def _centroide_grupo(inventario: list[dict[str, Any]]) -> tuple[float, float] | None:
    pares: list[tuple[float, float]] = []
    for lugar in inventario:
        if not isinstance(lugar, dict):
            continue
        extra = lugar.get("extra") if isinstance(lugar.get("extra"), dict) else {}
        lat = extra.get("latitude")
        lng = extra.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            pares.append((float(lat), float(lng)))
    if not pares:
        return None
    avg_lat = sum(p[0] for p in pares) / len(pares)
    avg_lng = sum(p[1] for p in pares) / len(pares)
    return avg_lat, avg_lng


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return R * c


def _coletar_cidades(membros: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for membro in membros:
        cidade = membro.get("cidade") if isinstance(membro, dict) else None
        if isinstance(cidade, str) and cidade.strip():
            counter[cidade.strip().lower()] += 1
    return counter


def _confidence_bonus(item: EnrichedItem) -> float:
    return min((item.confianca_enriquecimento or 0.0), 1.0) * 0.5


def _bad_status_penalty(item: EnrichedItem) -> float:
    if item.status_matching == StatusMatching.POSSIVELMENTE_FECHADO:
        return 5.0
    if item.status_matching == StatusMatching.DADOS_INCOMPLETOS:
        return 1.5
    return 0.0


def _to_card(
    scored: list[tuple[float, EnrichedItem]],
    *,
    id_prefix: str,
    titulo: str,
    motivo_template: str,
) -> GuiaIaSugestaoCard | None:
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    score, item = scored[0]
    if score <= 0:
        return None
    return GuiaIaSugestaoCard(
        id=id_prefix,
        titulo=titulo,
        motivo=motivo_template,
        nome=item.nome_oficial or item.extracted.nome_original,
        foto_url=item.foto_url,
        bairro=item.bairro_normalizado or item.extracted.bairro,
        cidade=item.cidade_normalizada or item.extracted.cidade,
        google_maps_uri=item.google_maps_uri,
        score=round(score, 3),
    )
