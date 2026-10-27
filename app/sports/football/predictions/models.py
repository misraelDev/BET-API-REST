"""Modelos del contrato de pronósticos de fútbol."""

from __future__ import annotations

from datetime import date, datetime
from datetime import date as date_type
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.prompts.models import PromptReference

from app.sports.football.predictions.catalog import (
    KickoffSource,
    Market,
    Period,
    SettlementStatus,
    TimingStatus,
    league_info,
    market_rule,
)

PREDICTION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$"
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
Side = Literal["home", "away"]


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field} debe incluir zona horaria u offset (por ejemplo "
            "2026-10-25T20:00:00-06:00). Se guarda en UTC."
        )
    return value


def _half_step(value: float) -> bool:
    return abs(value * 2 - round(value * 2)) < 1e-9


def _quarter_step(value: float) -> bool:
    return abs(value * 4 - round(value * 4)) < 1e-9


class PredictionSource(BaseModel):
    """Fuente consultada por el analista para respaldar su selección."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=2,
        max_length=120,
        description="Nombre de la fuente (ESPN, sitio del club, API, etc.).",
        examples=["ESPN"],
    )
    url: HttpUrl | None = Field(
        default=None,
        description="Enlace consultado. Opcional, pero recomendado para auditoría.",
        examples=["https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/summary?event=736644"],
    )
    note: str | None = Field(
        default=None,
        max_length=500,
        description="Nota sobre qué dato se tomó de esta fuente.",
        examples=["Estadísticas de córners y tarjetas del partido."],
    )


class FootballPredictionCreate(BaseModel):
    """Una selección atómica dentro de una carga por lotes.

    ``prediction_id`` es el identificador lógico y estable de la selección. Si
    se envía de nuevo con el mismo ``prediction_id``, la API crea una versión
    nueva (no sobrescribe). ``idempotency_key`` evita duplicados por reintentos.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "prediction_id": "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8",
                    "idempotency_key": "2026-10-24-liga-mx-123456-1x2-home",
                    "event_id": 736644,
                    "match_date": "2026-10-24",
                    "league": "liga_mx",
                    "home_team": "Pumas UNAM",
                    "away_team": "Necaxa",
                    "kickoff": "2026-10-24T20:00:00-06:00",
                    "market": "1x2",
                    "period": "full_time",
                    "selection": "home",
                    "probability": 58.0,
                    "confidence": 4,
                    "rationale": "Local con mejor forma y ventaja de localía.",
                    "sources": [
                        {
                            "name": "ESPN",
                            "url": "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/summary?event=736644",
                        }
                    ],
                    "analyst": "ana.garcia",
                    "method_version": "analista-v1",
                    "generated_at": "2026-10-24T10:30:00-06:00",
                }
            ]
        },
    )

    prediction_id: str | None = Field(
        default=None,
        pattern=PREDICTION_ID_PATTERN,
        description=(
            "Identificador lógico y estable de la selección. Si se omite, el "
            "servidor genera uno. Enviarlo de nuevo crea una versión nueva."
        ),
        examples=["3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8"],
    )
    idempotency_key: str = Field(
        pattern=IDEMPOTENCY_KEY_PATTERN,
        description=(
            "Clave única global en football_predictions (no por analista ni por "
            "lote). Un reintento con la misma clave y el mismo "
            "cuerpo devuelve la versión existente; con un cuerpo distinto se "
            "rechaza como conflicto."
        ),
        examples=["2026-10-24-liga-mx-123456-1x2-home"],
    )
    event_id: int = Field(
        gt=0,
        description="Identificador del partido en la fuente (ESPN).",
        examples=[736644],
    )
    match_date: date = Field(
        description=(
            "Fecha del partido en horario de Ciudad de México (UTC-6). Es el "
            "campo que filtra la jornada."
        ),
        examples=["2026-10-24"],
    )
    league: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
        description="Competición. Consulta el catálogo en /predictions/markets.",
        examples=["liga_mx"],
    )
    home_team: str = Field(
        min_length=1,
        max_length=120,
        description="Equipo local tal como lo reporta la fuente.",
        examples=["Pumas UNAM"],
    )
    away_team: str = Field(
        min_length=1,
        max_length=120,
        description="Equipo visitante tal como lo reporta la fuente.",
        examples=["Necaxa"],
    )
    kickoff: datetime | None = Field(
        default=None,
        description=(
            "Inicio del partido con offset. El servidor intenta verificarlo "
            "contra la fuente. Si no lo logra, conserva este valor como "
            "referencia, pero timing queda unverified."
        ),
        examples=["2026-10-24T20:00:00-06:00"],
    )
    market: Market = Field(
        description="Mercado de la selección.",
        examples=["1x2"],
    )
    period: Period = Field(
        default=Period.FULL_TIME,
        description=(
            "Periodo evaluado. full_time = regulación, sin alargue ni penales. "
            "second_half no acumula el primer tiempo. Las estadísticas se "
            "liquidan por mitad solo si la fuente proporciona ese periodo."
        ),
        examples=["full_time"],
    )
    selection: str | None = Field(
        default=None,
        description=(
            "Selección del mercado. 1x2: home/draw/away. Doble oportunidad: "
            "home_or_draw, home_or_away o draw_or_away. Hándicaps y más córners: "
            "home/away o home/draw/away. Over/under: over/under. BTTS: yes/no. "
            "Primer gol: home/away/none. Marcador exacto no usa este campo."
        ),
        examples=["home"],
    )
    line: float | None = Field(
        default=None,
        description=(
            "Línea del mercado. asian_handicap admite incrementos de 0.25; los "
            "demás mercados usan incrementos de 0.5. Para asian_handicap la "
            "línea se aplica al lado seleccionado; en european_handicap se "
            "aplica siempre al local. Over/under requiere línea positiva."
        ),
        examples=[-1.5],
    )
    team: Side | None = Field(
        default=None,
        description="Equipo para mercados por equipo (goles, córners, tarjetas, remates).",
        examples=["home"],
    )
    player: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        description="Nombre del jugador para mercados de jugador.",
        examples=["Guillermo Martínez"],
    )
    player_id: str | None = Field(
        default=None,
        max_length=64,
        description="Id del jugador en la fuente. Mejora la identificación.",
        examples=["329917"],
    )
    home_goals: int | None = Field(
        default=None,
        ge=0,
        le=20,
        description="Goles del local para marcador exacto.",
        examples=[2],
    )
    away_goals: int | None = Field(
        default=None,
        ge=0,
        le=20,
        description="Goles del visitante para marcador exacto.",
        examples=[1],
    )
    probability: float = Field(
        ge=0,
        le=100,
        description="Probabilidad declarada por el analista (0-100).",
        examples=[58.0],
    )
    confidence: int = Field(
        ge=1,
        le=5,
        description="Confianza en estrellas (1-5).",
        examples=[4],
    )
    rationale: str = Field(
        min_length=5,
        max_length=4000,
        description="Justificación de la selección.",
        examples=["Local con mejor forma y ventaja de localía."],
    )
    sources: list[PredictionSource] = Field(
        min_length=1,
        max_length=20,
        description="Fuentes consultadas. Se exige al menos una.",
    )
    analyst: str = Field(
        min_length=2,
        max_length=80,
        description="Identificador del analista que emite la selección.",
        examples=["ana.garcia"],
    )
    method_version: str = Field(
        min_length=1,
        max_length=40,
        description="Versión del método o modelo usado por el analista.",
        examples=["analista-v1"],
    )
    generated_at: datetime | None = Field(
        default=None,
        description=(
            "Hora en que el analista generó la selección, con offset. Se "
            "conserva aparte y nunca sustituye a received_at."
        ),
        examples=["2026-10-24T10:30:00-06:00"],
    )
    notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Nota libre para el análisis posterior.",
    )

    @field_validator("kickoff", "generated_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _aware(value, info.field_name)

    @field_validator("home_team", "away_team", "analyst", "method_version")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("El campo no puede estar vacío.")
        return cleaned

    @field_validator("rationale")
    @classmethod
    def _strip_rationale(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("La justificación debe tener al menos 5 caracteres.")
        return cleaned

    @field_validator("selection", "team", "player", "player_id", "notes")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @model_validator(mode="after")
    def _validate_market_contract(self) -> Self:
        rule = market_rule(self.market)

        if self.period not in rule.periods:
            allowed = ", ".join(period.value for period in rule.periods)
            raise ValueError(
                f"El mercado {self.market.value} no admite el periodo "
                f"{self.period.value}. Periodos válidos: {allowed}."
            )

        if self.home_team.casefold() == self.away_team.casefold():
            raise ValueError("home_team y away_team deben ser distintos.")

        if self.selection is not None:
            self.selection = self.selection.casefold()

        if self.line is not None:
            valid_step = (
                _quarter_step(self.line)
                if self.market == Market.ASIAN_HANDICAP
                else _half_step(self.line)
            )
            if not valid_step:
                raise ValueError(
                    "line debe ser múltiplo de 0.25 para asian_handicap y de "
                    "0.5 para los demás mercados."
                )
            if self.line == 0:
                raise ValueError("line no puede ser 0.")

        if rule.needs_line:
            if self.line is None:
                raise ValueError(f"El mercado {self.market.value} requiere line.")
            if rule.positive_line and self.line < 0.5:
                raise ValueError(
                    f"El mercado {self.market.value} requiere line >= 0.5."
                )
            minimum = 0.25 if self.market == Market.ASIAN_HANDICAP else 0.5
            if not rule.positive_line and abs(self.line) < minimum:
                raise ValueError(
                    f"El mercado {self.market.value} requiere |line| >= {minimum}."
                )
        elif self.line is not None:
            raise ValueError(f"El mercado {self.market.value} no usa line.")

        if rule.needs_team:
            if self.team is None:
                raise ValueError(f"El mercado {self.market.value} requiere team.")
        elif self.team is not None:
            raise ValueError(f"El mercado {self.market.value} no usa team.")

        if rule.needs_player:
            if self.player is None:
                raise ValueError(f"El mercado {self.market.value} requiere player.")
        elif self.player is not None:
            raise ValueError(
                f"El mercado {self.market.value} no usa player."
            )

        if rule.needs_score:
            if self.home_goals is None or self.away_goals is None:
                raise ValueError(
                    f"El mercado {self.market.value} requiere home_goals y "
                    "away_goals."
                )
        elif self.home_goals is not None or self.away_goals is not None:
            raise ValueError(
                f"El mercado {self.market.value} no usa home_goals ni away_goals."
            )

        if rule.selection_values:
            if self.selection is None:
                raise ValueError(
                    f"El mercado {self.market.value} requiere selection."
                )
            if self.selection not in rule.selection_values:
                allowed = ", ".join(rule.selection_values)
                raise ValueError(
                    f"selection inválida para {self.market.value}: "
                    f"{self.selection!r}. Valores permitidos: {allowed}."
                )
        elif self.selection is not None:
            raise ValueError(
                f"El mercado {self.market.value} no usa selection."
            )

        if self.player_id is not None and self.player is None:
            raise ValueError("player_id solo aplica cuando se envía player.")

        return self

    @property
    def selection_summary(self) -> str:
        """Etiqueta legible de la selección para confirmaciones y auditoría."""
        parts: list[str] = []
        if self.selection is not None:
            parts.append(self.selection)
        if self.team is not None:
            parts.append(f"team={self.team}")
        if self.player is not None:
            parts.append(f"player={self.player}")
        if self.line is not None:
            parts.append(f"line={self.line:+g}")
        if self.home_goals is not None and self.away_goals is not None:
            parts.append(f"score={self.home_goals}-{self.away_goals}")
        return " ".join(parts)


class FootballPredictionBatchRequest(BaseModel):
    """Carga por lotes. Cada elemento se guarda y evalúa por separado."""

    model_config = ConfigDict(extra="forbid")

    analysis_prompt_version_id: str = Field(
        pattern=r"^[A-Fa-f0-9]{32}$",
        description=(
            "version_id exacto del prompt de análisis resuelto al inicio de "
            "la ejecución. Se fija para todas las selecciones del lote."
        ),
        examples=["3be3ffee060a4f01b01057c32f5ae197"],
    )

    items: list[FootballPredictionCreate] = Field(
        min_length=1,
        max_length=100,
        description="Selecciones a registrar. Máximo 100 por petición.",
    )

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        keys = [item.idempotency_key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "idempotency_key debe ser única dentro de la petición."
            )
        prediction_ids = [
            item.prediction_id for item in self.items if item.prediction_id
        ]
        if len(prediction_ids) != len(set(prediction_ids)):
            raise ValueError(
                "prediction_id debe ser único dentro de la petición; para "
                "versionar una selección envía una petición por versión."
            )
        return self


class StoredMatch(BaseModel):
    event_id: int
    date: date_type = Field(description="Fecha en CDMX (UTC-6).")
    declared_date: date_type | None = Field(
        default=None,
        description="Fecha que declaró el analista, conservada para auditoría.",
    )
    league: str
    league_name: str
    country: str | None = None
    home_team: str
    away_team: str
    kickoff: datetime | None = Field(
        default=None, description="Inicio en UTC, cuando se conoce."
    )
    kickoff_source: KickoffSource
    kickoff_verified: bool


class StoredTiming(BaseModel):
    status: TimingStatus
    received_before_kickoff: bool | None = None


class SettlementSource(BaseModel):
    name: str
    url: HttpUrl | None = None
    retrieved_at: datetime


class PredictionSettlement(BaseModel):
    status: SettlementStatus
    observed: dict[str, Any] = Field(
        description="Datos observados que sustentan la liquidación."
    )
    summary: str
    reason: str | None = None
    source: SettlementSource
    settled_at: datetime
    rule_version: str


class StoredPrediction(BaseModel):
    document_id: str
    prediction_id: str
    version: int
    version_id: str
    is_current: bool
    supersedes_version_id: str | None = None
    event_id: int
    match: StoredMatch
    market: Market
    period: Period
    selection: str | None = None
    line: float | None = None
    team: Side | None = None
    player: str | None = None
    player_id: str | None = None
    home_goals: int | None = None
    away_goals: int | None = None
    probability: float
    confidence: int
    rationale: str
    sources: list[PredictionSource]
    analyst: str
    method_version: str
    analysis_prompt: PromptReference | None = Field(
        default=None,
        description=(
            "Referencia exacta al prompt de análisis. Null/ausente en registros "
            "históricos cuyo prompt no se puede verificar."
        ),
    )
    generated_at: datetime | None = None
    received_at: datetime
    timing: StoredTiming
    settlement_status: SettlementStatus
    settlement: PredictionSettlement | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class FootballPredictionBatchItemResult(BaseModel):
    prediction_id: str | None = None
    version: int | None = None
    version_id: str | None = None
    idempotency_key: str
    status: Literal["created", "replayed", "rejected"]
    error: str | None = None
    analyst: str
    probability: float
    received_before_kickoff: bool | None = None
    record: StoredPrediction | None = Field(
        default=None,
        description="Versión persistida devuelta en creaciones y reintentos.",
    )


class FootballPredictionBatchResponse(BaseModel):
    received_at: datetime
    total: int
    created: int
    replayed: int
    rejected: int
    items: list[FootballPredictionBatchItemResult]


class FootballPredictionListResponse(BaseModel):
    items: list[StoredPrediction]
    page: int
    page_size: int
    total: int


class FootballPredictionDetailResponse(BaseModel):
    prediction_id: str
    total_versions: int
    current_version: int | None = None
    latest_verified_pre_match_version: int | None = None
    latest_verified_pre_match: StoredPrediction | None = None
    versions: list[StoredPrediction]


class FootballPredictionEvaluationCreate(BaseModel):
    """Diagnóstico posterior del analista. No modifica el pronóstico original."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
                    "evaluation_prompt_version_id": "90fcd2406d3e4cb2bea14502e1247311",
                    "analyst": "ana.garcia",
                    "diagnosis": "La lectura del primer tiempo fue acertada.",
                    "learnings": ["Revisar alineaciones antes del cierre."],
                    "sources": [{"name": "ESPN"}],
                }
            ]
        },
    )

    version_id: str = Field(
        pattern=r"^[A-Fa-f0-9]{32}$",
        min_length=8,
        max_length=64,
        description="Identificador exacto de la versión evaluada.",
        examples=["9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f"],
    )
    evaluation_prompt_version_id: str = Field(
        pattern=r"^[A-Fa-f0-9]{32}$",
        description=(
            "version_id exacto del prompt de evaluación usado. No equivale a "
            "la versión del método ni a la versión del pronóstico evaluado."
        ),
        examples=["90fcd2406d3e4cb2bea14502e1247311"],
    )
    analyst: str = Field(
        min_length=2,
        max_length=80,
        description="Analista que escribe la evaluación.",
        examples=["ana.garcia"],
    )
    diagnosis: str = Field(
        min_length=10,
        max_length=4000,
        description="Qué pasó y por qué la selección acertó o falló.",
    )
    learnings: list[str] = Field(
        min_length=1,
        max_length=20,
        description="Aprendizajes accionables para próximas selecciones.",
    )
    sources: list[PredictionSource] = Field(
        min_length=1,
        max_length=20,
        description="Fuentes usadas para la evaluación posterior.",
    )
    outcome_comment: str | None = Field(
        default=None,
        max_length=1000,
        description="Comentario libre sobre el resultado observado.",
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Etiquetas para agrupar aprendizajes.",
    )


class StoredEvaluation(BaseModel):
    evaluation_id: str
    prediction_id: str
    version: int
    version_id: str
    evaluation_prompt: PromptReference | None = Field(
        default=None,
        description=(
            "Referencia exacta al prompt de evaluación. Null/ausente en "
            "evaluaciones históricas sin evidencia verificable."
        ),
    )
    analyst: str
    diagnosis: str
    learnings: list[str]
    sources: list[PredictionSource]
    outcome_comment: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class FootballEvaluationListResponse(BaseModel):
    items: list[StoredEvaluation]
    page: int
    page_size: int
    total: int


class FootballMarketRuleResponse(BaseModel):
    market: Market
    label: str
    periods: list[Period]
    selection_values: list[str]
    requires_line: bool
    requires_team: bool
    requires_player: bool
    requires_score: bool
    line_must_be_positive: bool
    allowed_line_steps: list[float]
    settlement_rule: str


class FootballLeagueCatalogItem(BaseModel):
    code: str
    name: str
    country: str
    type: str = "league"
    active: bool = True
    registration_available: bool = True
    providers: dict[str, Any] | None = None
    query_available: bool = True
    automatic_settlement_available: bool = True


class FootballMarketCatalogResponse(BaseModel):
    rule_version: str
    periods: dict[str, str]
    settlement_statuses: dict[str, str]
    leagues: list[FootballLeagueCatalogItem]
    markets: list[FootballMarketRuleResponse]


class FootballResultsUpdateError(BaseModel):
    event_id: int | None = None
    stage: str
    message: str


class FootballSettlementSummary(BaseModel):
    predictions_matched: int
    predictions_settled: int
    predictions_updated: int
    predictions_pending: int
    unmatched_event_ids: list[str]
    errors: list[FootballResultsUpdateError]


def _source_from_stored(value: Any) -> Any:
    """Normaliza la fuente guardada en Mongo al modelo público."""
    if value is None:
        return None
    if isinstance(value, PredictionSource):
        return value
    return value


__all__ = [
    "FootballEvaluationListResponse",
    "FootballLeagueCatalogItem",
    "FootballMarketCatalogResponse",
    "FootballMarketRuleResponse",
    "FootballPredictionBatchItemResult",
    "FootballPredictionBatchRequest",
    "FootballPredictionBatchResponse",
    "FootballPredictionCreate",
    "FootballPredictionDetailResponse",
    "FootballPredictionEvaluationCreate",
    "FootballPredictionListResponse",
    "FootballResultsUpdateError",
    "FootballSettlementSummary",
    "PredictionSettlement",
    "PredictionSource",
    "SettlementSource",
    "StoredEvaluation",
    "StoredMatch",
    "StoredPrediction",
    "StoredTiming",
]
