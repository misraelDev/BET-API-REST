"""Catálogo de ligas, mercados y periodos soportados por pronósticos.

El catálogo es la única fuente de verdad para:

* traducir el código de liga a su ``slug`` de ESPN;
* decidir qué periodos admite cada mercado;
* validar la selección, línea, equipo y jugador de cada mercado;
* documentar la regla de liquidación que aplica el motor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FootballLeague(StrEnum):
    """Competiciones consultables y liquidables con el nuevo contrato."""

    LIGA_MX = "liga_mx"
    LIGA_EXPANSION_MX = "liga_expansion_mx"
    BRASILEIRAO = "brasileirao"
    LEAGUES_CUP = "leagues_cup"
    MLS = "mls"
    LA_LIGA = "la_liga"
    PREMIER_LEAGUE = "premier_league"
    SERIE_A = "serie_a"
    BUNDESLIGA = "bundesliga"
    LIGUE_1 = "ligue_1"
    CHAMPIONS_LEAGUE = "champions_league"
    EUROPA_LEAGUE = "europa_league"
    LIBERTADORES = "libertadores"
    SUDAMERICANA = "sudamericana"
    LIGA_BETPLAY = "liga_betplay"
    LIGA_PROFESIONAL_ARGENTINA = "liga_profesional_argentina"
    PRIMERA_DIVISION_CHILE = "primera_division_chile"
    LIGA_1_PERU = "liga_1_peru"
    LIGAPRO_ECUADOR = "ligapro_ecuador"
    PRIMERA_DIVISION_URUGUAY = "primera_division_uruguay"


@dataclass(frozen=True)
class LeagueInfo:
    code: FootballLeague
    name: str
    espn_slug: str
    country: str


LEAGUES: dict[FootballLeague, LeagueInfo] = {
    FootballLeague.LIGA_MX: LeagueInfo(
        FootballLeague.LIGA_MX, "Liga MX", "mex.1", "México"
    ),
    FootballLeague.LIGA_EXPANSION_MX: LeagueInfo(
        FootballLeague.LIGA_EXPANSION_MX,
        "Liga de Expansión MX",
        "mex.2",
        "México",
    ),
    FootballLeague.BRASILEIRAO: LeagueInfo(
        FootballLeague.BRASILEIRAO, "Brasileirão Betano", "bra.1", "Brasil"
    ),
    FootballLeague.LEAGUES_CUP: LeagueInfo(
        FootballLeague.LEAGUES_CUP,
        "Leagues Cup",
        "concacaf.leagues.cup",
        "Norteamérica",
    ),
    FootballLeague.MLS: LeagueInfo(
        FootballLeague.MLS, "MLS", "usa.1", "Estados Unidos"
    ),
    FootballLeague.LA_LIGA: LeagueInfo(
        FootballLeague.LA_LIGA, "LaLiga", "esp.1", "España"
    ),
    FootballLeague.PREMIER_LEAGUE: LeagueInfo(
        FootballLeague.PREMIER_LEAGUE,
        "Premier League",
        "eng.1",
        "Inglaterra",
    ),
    FootballLeague.SERIE_A: LeagueInfo(
        FootballLeague.SERIE_A, "Serie A", "ita.1", "Italia"
    ),
    FootballLeague.BUNDESLIGA: LeagueInfo(
        FootballLeague.BUNDESLIGA, "Bundesliga", "ger.1", "Alemania"
    ),
    FootballLeague.LIGUE_1: LeagueInfo(
        FootballLeague.LIGUE_1, "Ligue 1", "fra.1", "Francia"
    ),
    FootballLeague.CHAMPIONS_LEAGUE: LeagueInfo(
        FootballLeague.CHAMPIONS_LEAGUE,
        "UEFA Champions League",
        "uefa.champions",
        "Europa",
    ),
    FootballLeague.EUROPA_LEAGUE: LeagueInfo(
        FootballLeague.EUROPA_LEAGUE,
        "UEFA Europa League",
        "uefa.europa",
        "Europa",
    ),
    FootballLeague.LIBERTADORES: LeagueInfo(
        FootballLeague.LIBERTADORES,
        "CONMEBOL Libertadores",
        "conmebol.libertadores",
        "Sudamérica",
    ),
    FootballLeague.SUDAMERICANA: LeagueInfo(
        FootballLeague.SUDAMERICANA,
        "CONMEBOL Sudamericana",
        "conmebol.sudamericana",
        "Sudamérica",
    ),
    FootballLeague.LIGA_BETPLAY: LeagueInfo(
        FootballLeague.LIGA_BETPLAY,
        "Liga BetPlay",
        "col.1",
        "Colombia",
    ),
    FootballLeague.LIGA_PROFESIONAL_ARGENTINA: LeagueInfo(
        FootballLeague.LIGA_PROFESIONAL_ARGENTINA,
        "Liga Profesional Argentina",
        "arg.1",
        "Argentina",
    ),
    FootballLeague.PRIMERA_DIVISION_CHILE: LeagueInfo(
        FootballLeague.PRIMERA_DIVISION_CHILE,
        "Primera División de Chile",
        "chi.1",
        "Chile",
    ),
    FootballLeague.LIGA_1_PERU: LeagueInfo(
        FootballLeague.LIGA_1_PERU, "Liga 1", "per.1", "Perú"
    ),
    FootballLeague.LIGAPRO_ECUADOR: LeagueInfo(
        FootballLeague.LIGAPRO_ECUADOR, "LigaPro", "ecu.1", "Ecuador"
    ),
    FootballLeague.PRIMERA_DIVISION_URUGUAY: LeagueInfo(
        FootballLeague.PRIMERA_DIVISION_URUGUAY,
        "Primera División de Uruguay",
        "uru.1",
        "Uruguay",
    ),
}

ESPN_SLUGS: tuple[str, ...] = tuple(
    dict.fromkeys(info.espn_slug for info in LEAGUES.values())
)


class Period(StrEnum):
    FULL_TIME = "full_time"
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"


PERIOD_LABELS: dict[Period, str] = {
    Period.FULL_TIME: "Tiempo completo (90 minutos + añadido, sin alargue ni penales)",
    Period.FIRST_HALF: "Primer tiempo",
    Period.SECOND_HALF: "Segundo tiempo (no acumulado)",
}

GOALS_PERIODS: tuple[Period, ...] = (
    Period.FULL_TIME,
    Period.FIRST_HALF,
    Period.SECOND_HALF,
)
FULL_TIME_ONLY: tuple[Period, ...] = (Period.FULL_TIME,)


class Market(StrEnum):
    ONE_X_TWO = "1x2"
    DOUBLE_CHANCE = "double_chance"
    ASIAN_HANDICAP = "asian_handicap"
    EUROPEAN_HANDICAP = "european_handicap"
    TOTAL_GOALS = "total_goals"
    TEAM_TOTAL_GOALS = "team_total_goals"
    BTTS = "btts"
    CORNERS_TOTAL = "corners_total"
    CORNERS_TEAM = "corners_team"
    CORNERS_HANDICAP = "corners_handicap"
    CORNERS_MOST = "corners_most"
    CARDS_TOTAL = "cards_total"
    CARDS_TEAM = "cards_team"
    CARDS_PLAYER = "cards_player"
    EXACT_SCORE = "exact_score"
    FIRST_TEAM_TO_SCORE = "first_team_to_score"
    SHOTS_TOTAL = "shots_total"
    SHOTS_TEAM = "shots_team"
    SHOTS_PLAYER = "shots_player"
    SHOTS_ON_TARGET_TOTAL = "shots_on_target_total"
    SHOTS_ON_TARGET_TEAM = "shots_on_target_team"
    SHOTS_ON_TARGET_PLAYER = "shots_on_target_player"


MARKET_1X2: tuple[str, ...] = ("home", "draw", "away")
MARKET_DOUBLE_CHANCE: tuple[str, ...] = (
    "home_or_draw",
    "home_or_away",
    "draw_or_away",
)
MARKET_OVER_UNDER: tuple[str, ...] = ("over", "under")
MARKET_BTTS: tuple[str, ...] = ("yes", "no")
MARKET_FIRST_TEAM: tuple[str, ...] = ("home", "away", "none")
MARKET_SIDES: tuple[str, ...] = ("home", "away")


@dataclass(frozen=True)
class MarketRule:
    market: Market
    label: str
    periods: tuple[Period, ...]
    selection_values: tuple[str, ...]
    needs_line: bool = False
    needs_team: bool = False
    needs_player: bool = False
    needs_score: bool = False
    positive_line: bool = False
    settlement_rule: str = ""


_OU_RULE = (
    "Se compara el total observado con la línea. Si el total es mayor que la "
    "línea, gana «over»; si es menor, gana «under». Con línea entera y total "
    "exactamente igual, el estado es «reembolso»."
)
_HANDICAP_RULE = (
    "La línea se suma al marcador del equipo elegido. Si el resultado ajustado "
    "es positivo gana la selección; si es negativo pierde; si es cero, "
    "«reembolso» en hándicap asiático y «fallado» en hándicap europeo (el "
    "empate ajustado es un resultado perdedor en el hándicap europeo de tres "
    "vías). La línea debe ser múltiplo de 0.5; no se admiten líneas de cuartos "
    "(0.25 / 0.75) en esta entrega."
)

MARKET_RULES: dict[Market, MarketRule] = {
    Market.ONE_X_TWO: MarketRule(
        Market.ONE_X_TWO,
        "Ganador (1X2)",
        GOALS_PERIODS,
        MARKET_1X2,
        settlement_rule=(
            "Gana la selección cuyo resultado coincide con el marcador del "
            "periodo: local, empate o visitante."
        ),
    ),
    Market.DOUBLE_CHANCE: MarketRule(
        Market.DOUBLE_CHANCE,
        "Doble oportunidad",
        GOALS_PERIODS,
        MARKET_DOUBLE_CHANCE,
        settlement_rule=(
            "Gana la selección si el resultado del periodo está entre las dos "
            "opciones elegidas (local/empate, local/visitante o empate/visitante)."
        ),
    ),
    Market.ASIAN_HANDICAP: MarketRule(
        Market.ASIAN_HANDICAP,
        "Hándicap asiático",
        GOALS_PERIODS,
        MARKET_SIDES,
        needs_line=True,
        settlement_rule=_HANDICAP_RULE,
    ),
    Market.EUROPEAN_HANDICAP: MarketRule(
        Market.EUROPEAN_HANDICAP,
        "Hándicap europeo",
        GOALS_PERIODS,
        MARKET_SIDES,
        needs_line=True,
        settlement_rule=_HANDICAP_RULE,
    ),
    Market.TOTAL_GOALS: MarketRule(
        Market.TOTAL_GOALS,
        "Goles totales",
        GOALS_PERIODS,
        MARKET_OVER_UNDER,
        needs_line=True,
        positive_line=True,
        settlement_rule=_OU_RULE,
    ),
    Market.TEAM_TOTAL_GOALS: MarketRule(
        Market.TEAM_TOTAL_GOALS,
        "Goles por equipo",
        GOALS_PERIODS,
        MARKET_OVER_UNDER,
        needs_line=True,
        needs_team=True,
        positive_line=True,
        settlement_rule=(
            "Se aplica la regla de over/under a los goles del equipo indicado "
            "en el periodo. " + _OU_RULE
        ),
    ),
    Market.BTTS: MarketRule(
        Market.BTTS,
        "Ambos equipos anotan",
        GOALS_PERIODS,
        MARKET_BTTS,
        settlement_rule=(
            "«Sí» gana si ambos equipos anotan al menos un gol en el periodo; "
            "«no» gana en cualquier otro caso (incluido 0-0)."
        ),
    ),
    Market.CORNERS_TOTAL: MarketRule(
        Market.CORNERS_TOTAL,
        "Córners totales",
        FULL_TIME_ONLY,
        MARKET_OVER_UNDER,
        needs_line=True,
        positive_line=True,
        settlement_rule=(
            "Solo tiempo completo (las fuentes no separan córners por tiempo). "
            + _OU_RULE
        ),
    ),
    Market.CORNERS_TEAM: MarketRule(
        Market.CORNERS_TEAM,
        "Córners por equipo",
        FULL_TIME_ONLY,
        MARKET_OVER_UNDER,
        needs_line=True,
        needs_team=True,
        positive_line=True,
        settlement_rule=(
            "Solo tiempo completo. " + _OU_RULE
        ),
    ),
    Market.CORNERS_HANDICAP: MarketRule(
        Market.CORNERS_HANDICAP,
        "Hándicap de córners",
        FULL_TIME_ONLY,
        MARKET_SIDES,
        needs_line=True,
        settlement_rule=(
            "Solo tiempo completo. La línea se suma a los córners del equipo "
            "elegido: margen ajustado positivo gana, negativo pierde y cero es "
            "«reembolso». La línea debe ser múltiplo de 0.5."
        ),
    ),
    Market.CORNERS_MOST: MarketRule(
        Market.CORNERS_MOST,
        "Más córners",
        FULL_TIME_ONLY,
        ("home", "draw", "away"),
        settlement_rule=(
            "Solo tiempo completo. Gana el equipo con más córners; si ambos "
            "empatan, el estado es «reembolso»."
        ),
    ),
    Market.CARDS_TOTAL: MarketRule(
        Market.CARDS_TOTAL,
        "Tarjetas totales",
        GOALS_PERIODS,
        MARKET_OVER_UNDER,
        needs_line=True,
        positive_line=True,
        settlement_rule=(
            "Cada tarjeta mostrada cuenta 1. Una segunda amarilla se cuenta "
            "como amarilla + roja (2) cuando la fuente reporta el evento como "
            "«segunda amarilla»; si la amarilla previa aparece como un evento "
            "aparte, suma 1 adicional. Una roja directa cuenta 1. "
            "El total es amarillas + rojas. " + _OU_RULE
        ),
    ),
    Market.CARDS_TEAM: MarketRule(
        Market.CARDS_TEAM,
        "Tarjetas por equipo",
        GOALS_PERIODS,
        MARKET_OVER_UNDER,
        needs_line=True,
        needs_team=True,
        positive_line=True,
        settlement_rule=(
            "Se aplica el conteo de tarjetas al equipo indicado. " + _OU_RULE
        ),
    ),
    Market.CARDS_PLAYER: MarketRule(
        Market.CARDS_PLAYER,
        "Tarjetas por jugador",
        GOALS_PERIODS,
        MARKET_OVER_UNDER,
        needs_line=True,
        needs_player=True,
        positive_line=True,
        settlement_rule=(
            "Se aplica el conteo de tarjetas al jugador indicado. Si el jugador "
            "no participó y la plantilla está disponible, su total es 0. Si no "
            "hay datos verificables del jugador, el estado es «no_evaluable»."
        ),
    ),
    Market.EXACT_SCORE: MarketRule(
        Market.EXACT_SCORE,
        "Marcador exacto",
        GOALS_PERIODS,
        (),
        needs_score=True,
        settlement_rule=(
            "Gana si los goles del local y del visitante en el periodo "
            "coinciden exactamente con los declarados."
        ),
    ),
    Market.FIRST_TEAM_TO_SCORE: MarketRule(
        Market.FIRST_TEAM_TO_SCORE,
        "Primer equipo en anotar",
        GOALS_PERIODS,
        MARKET_FIRST_TEAM,
        settlement_rule=(
            "Se ordenan los goles del periodo por tiempo. Gana el equipo que "
            "anotó primero; «none» gana si no hubo goles. Un autogol se acredita "
            "al equipo contrario al que reporta la fuente."
        ),
    ),
    Market.SHOTS_TOTAL: MarketRule(
        Market.SHOTS_TOTAL,
        "Remates totales",
        FULL_TIME_ONLY,
        MARKET_OVER_UNDER,
        needs_line=True,
        positive_line=True,
        settlement_rule=(
            "Solo tiempo completo. «Remate» es el valor totalShots que ESPN "
            "publica para el equipo (todos los intentos que la fuente cuenta); "
            "los bloqueados se publican aparte en blockedShots y no se suman. "
            + _OU_RULE
        ),
    ),
    Market.SHOTS_TEAM: MarketRule(
        Market.SHOTS_TEAM,
        "Remates por equipo",
        FULL_TIME_ONLY,
        MARKET_OVER_UNDER,
        needs_line=True,
        needs_team=True,
        positive_line=True,
        settlement_rule="Solo tiempo completo. " + _OU_RULE,
    ),
    Market.SHOTS_PLAYER: MarketRule(
        Market.SHOTS_PLAYER,
        "Remates por jugador",
        FULL_TIME_ONLY,
        MARKET_OVER_UNDER,
        needs_line=True,
        needs_player=True,
        positive_line=True,
        settlement_rule=(
            "Solo tiempo completo. Si el jugador no participó y la plantilla "
            "está disponible, su total es 0. " + _OU_RULE
        ),
    ),
    Market.SHOTS_ON_TARGET_TOTAL: MarketRule(
        Market.SHOTS_ON_TARGET_TOTAL,
        "Remates a puerta totales",
        FULL_TIME_ONLY,
        MARKET_OVER_UNDER,
        needs_line=True,
        positive_line=True,
        settlement_rule=(
            "Solo tiempo completo. «Remate a puerta» es el valor "
            "shotsOnTarget de ESPN: remate dirigido entre los tres palos que "
            "el portero detiene o que termina en gol. " + _OU_RULE
        ),
    ),
    Market.SHOTS_ON_TARGET_TEAM: MarketRule(
        Market.SHOTS_ON_TARGET_TEAM,
        "Remates a puerta por equipo",
        FULL_TIME_ONLY,
        MARKET_OVER_UNDER,
        needs_line=True,
        needs_team=True,
        positive_line=True,
        settlement_rule="Solo tiempo completo. " + _OU_RULE,
    ),
    Market.SHOTS_ON_TARGET_PLAYER: MarketRule(
        Market.SHOTS_ON_TARGET_PLAYER,
        "Remates a puerta por jugador",
        FULL_TIME_ONLY,
        MARKET_OVER_UNDER,
        needs_line=True,
        needs_player=True,
        positive_line=True,
        settlement_rule=(
            "Solo tiempo completo. Si el jugador no participó y la plantilla "
            "está disponible, su total es 0. " + _OU_RULE
        ),
    ),
}


class SettlementStatus(StrEnum):
    PENDIENTE = "pendiente"
    ACERTADO = "acertado"
    FALLADO = "fallado"
    REEMBOLSO = "reembolso"
    ANULADO = "anulado"
    NO_EVALUABLE = "no_evaluable"


SETTLEMENT_STATUS_LABELS: dict[SettlementStatus, str] = {
    SettlementStatus.PENDIENTE: "El partido no ha terminado o falta información.",
    SettlementStatus.ACERTADO: "La selección coincidió con el resultado observado.",
    SettlementStatus.FALLADO: "La selección no coincidió con el resultado observado.",
    SettlementStatus.REEMBOLSO: "El mercado se anuló por empate en la línea o en el mercado.",
    SettlementStatus.ANULADO: "El partido se canceló o abandonó.",
    SettlementStatus.NO_EVALUABLE: "La fuente no permite verificar el mercado o periodo.",
}


class TimingStatus(StrEnum):
    PRE_MATCH = "pre_match"
    LATE = "late"
    UNVERIFIED = "unverified"


class KickoffSource(StrEnum):
    PROVIDER = "provider"
    REQUEST = "request"
    UNKNOWN = "unknown"


RULE_VERSION = "football-settlement-v1"


def league_info(league: FootballLeague | str) -> LeagueInfo:
    """Devuelve la información de la liga aceptando el código o el enum."""
    return LEAGUES[FootballLeague(str(league))]


def market_rule(market: Market | str) -> MarketRule:
    return MARKET_RULES[Market(str(market))]


def market_catalog() -> list[dict[str, object]]:
    """Catálogo serializable para el endpoint de consulta."""
    return [
        {
            "market": rule.market.value,
            "label": rule.label,
            "periods": [period.value for period in rule.periods],
            "selection_values": list(rule.selection_values),
            "requires_line": rule.needs_line,
            "requires_team": rule.needs_team,
            "requires_player": rule.needs_player,
            "requires_score": rule.needs_score,
            "line_must_be_positive": rule.positive_line,
            "settlement_rule": rule.settlement_rule,
        }
        for rule in MARKET_RULES.values()
    ]


def league_catalog() -> list[dict[str, str]]:
    return [
        {
            "code": info.code.value,
            "name": info.name,
            "country": info.country,
            "source": f"ESPN ({info.espn_slug})",
        }
        for info in LEAGUES.values()
    ]


__all__ = [
    "ESPN_SLUGS",
    "FULL_TIME_ONLY",
    "GOALS_PERIODS",
    "KickoffSource",
    "LEAGUES",
    "LeagueInfo",
    "MARKET_RULES",
    "Market",
    "MarketRule",
    "PERIOD_LABELS",
    "Period",
    "RULE_VERSION",
    "SETTLEMENT_STATUS_LABELS",
    "SettlementStatus",
    "TimingStatus",
    "FootballLeague",
    "league_catalog",
    "league_info",
    "market_catalog",
    "market_rule",
]
