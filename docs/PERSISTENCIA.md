# Persistencia

## Registro manual

`POST /api/v1/records` ejecuta un `upsert` en la colección configurada con
`MONGODB_COLLECTION` (por defecto `predictions`). El documento conserva el
subdocumento `prediction` con la misma forma que usaban las predicciones, para
que `/results` y la liquidación sigan funcionando sin migrar datos.

La identidad se construye con:

```text
sport + event_id + requested_date + model_version ("manual-v1")
```

En tenis no se incluye `model_version`, igual que antes. Registrar dos veces el
mismo partido con la misma fecha **actualiza** el documento; no crea
duplicados. El `created_at` se fija en el primer registro y `updated_at` cambia
en cada actualización.

Campos del documento:

| Campo | Contenido |
| --- | --- |
| `sport` | Deporte. |
| `event_id` | Id del partido (derivado en béisbol si no se envía). |
| `requested_date` | Fecha del partido. |
| `model_version` | `manual-v1`. |
| `provider` | `manual`. |
| `timezone` | Zona declarada por el analista. |
| `prediction` | Pick, probabilidad, mercados y datos de equipos. |
| `settlement` | Resultado de la liquidación, si ya se ejecutó. |
| `created_at` / `updated_at` | Marcas de tiempo. |

## Pronósticos versionados de fútbol

El contrato nuevo usa **dos colecciones independientes** del registro manual:

| Colección | Variable | Contenido |
| --- | --- | --- |
| `football_predictions` | `MONGODB_FOOTBALL_PREDICTIONS_COLLECTION` | Una selección atómica por documento y versión. |
| `football_prediction_evaluations` | `MONGODB_FOOTBALL_EVALUATIONS_COLLECTION` | Diagnósticos posteriores del analista. |

No hay `upsert`: cada versión es un `insert` nuevo. La versión anterior se marca
`is_current=false` y la nueva guarda `supersedes_version_id`.

`received_at` es hora del servidor. Un kickoff declarado sin confirmación de
ESPN se conserva como referencia, pero se etiqueta `unverified` y no permite
acreditar timing prepartido. El detalle incluye `latest_verified_pre_match`, que
busca entre el historial aunque la versión actual haya llegado tarde.

### Documento de pronóstico

| Campo | Contenido |
| --- | --- |
| `prediction_id` | Identificador lógico y estable de la selección. |
| `version` / `version_id` | Número consecutivo e identificador único de la versión. |
| `is_current` | `true` solo en la versión vigente. |
| `supersedes_version_id` | Versión anterior, si existe. |
| `idempotency_key` / `request_hash` | Clave del envío y huella del cuerpo. |
| `event_id` | Partido. |
| `match` | `event_id`, `date` (CDMX), `declared_date`, liga, equipos, `kickoff` en UTC, `kickoff_source` y `kickoff_verified`. |
| `market`, `period` | Mercado y periodo evaluado. |
| `selection`, `line`, `team`, `player`, `player_id`, `home_goals`, `away_goals` | Identidad de la selección. |
| `probability`, `confidence` | Probabilidad 0–100 y confianza 1–5. |
| `rationale`, `sources` | Justificación y fuentes. |
| `analyst`, `method_version` | Autor y método. |
| `generated_at` | Hora declarada por el analista, en UTC. |
| `received_at` | Hora del servidor, en UTC. Es la referencia de `timing`. |
| `timing` | `status` (`pre_match`, `late`, `unverified`) y `received_before_kickoff`. |
| `settlement_status` / `settlement` | Estado y evidencia de la liquidación. |
| `created_at` / `updated_at` | Marcas de tiempo en UTC. |

`received_at` y `created_at` se fijan en el primer insert. `updated_at` cambia
cuando se escribe la liquidación.

### Índices

| Índice | Clave | Único |
| --- | --- | --- |
| `prediction_idempotency` | `idempotency_key` | Sí |
| `prediction_version` | `prediction_id` + `version` | Sí |
| `prediction_current` | `prediction_id` + `is_current` | No |
| `prediction_single_current` | `prediction_id` parcial (`is_current=true`) | Sí |
| `prediction_match_date` | `match.date` + `is_current` | No |
| `prediction_event` | `event_id` + `is_current` | No |
| `prediction_analyst` | `analyst` + `is_current` | No |
| `prediction_market` | `market` + `is_current` | No |
| `prediction_settlement_status` | `settlement_status` | No |
| `prediction_timing` | `timing.status` | No |

La idempotencia tiene alcance global en `football_predictions`: la clave única
reserva el reintento sin importar lote o analista. El índice compuesto por
`prediction_id` + `version` impide repetir una versión. La promoción a vigente
compara atómicamente el `version_id` previo (`is_current=true`) y el índice
parcial único impide dos vigentes. Si la comparación pierde una carrera, la
solicitud no modifica la versión ganadora; el cliente puede reintentar con la
misma clave.

### Liquidación

`POST /api/v1/football/results/update` escribe en la versión vigente:

```json
{
  "status": "acertado",
  "observed": {
    "period": "full_time",
    "home_goals": 2,
    "away_goals": 1,
    "total_goals": 3,
    "score": "2-1",
    "winner": "home"
  },
  "summary": "El local ganó 2-1.",
  "reason": null,
  "source": {
    "name": "ESPN public summary",
    "url": "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/summary?event=736644",
    "retrieved_at": "2026-10-25T05:00:00Z"
  },
  "settled_at": "2026-10-25T05:00:05Z",
  "rule_version": "football-settlement-v2"
}
```

La liquidación es idempotente: si el estado y la evidencia observada no cambian,
no se reescribe el documento. El pronóstico original (selección, probabilidad,
confianza, fecha y fuentes) nunca se modifica.

Los estados posibles son `pendiente`, `acertado`, `fallado`, `reembolso`,
`media_ganancia`, `media_perdida`, `anulado` y `no_evaluable`. La colección heredada de `MONGODB_COLLECTION` sigue
usando `won`, `lost` y `push`; son mecanismos distintos y no se mezclan.

### Evaluaciones posteriores

Cada evaluación vive en `football_prediction_evaluations` y guarda
`evaluation_id`, `prediction_id`, `version`, `version_id`, `analyst`,
`diagnosis`, `learnings`, `sources`, `outcome_comment`, `tags` y `created_at`.
La petición requiere `version_id`; la evaluación almacena también `version`.
Los índices únicos `evaluation_identity` y `evaluation_version_identity` evitan
duplicar una evaluación del mismo analista y la misma versión exacta. Otra
persona sí puede aportar su propia evaluación.

La evaluación no sustituye la liquidación oficial ni escribe en el documento
del pronóstico.

## Prompts versionados

La colección independiente `prompts` (configurable con
`MONGODB_PROMPTS_COLLECTION`) almacena una secuencia por `(sport, prompt_type)`.
Los tipos son `analysis` y `evaluation`; los deportes aceptados son `football`,
`nba`, `baseball` y `tennis`.

Cada publicación crea un documento inmutable con `version`, `version_id`, texto,
autor, resumen de cambios y referencia `supersedes_version_id`. No existe
actualización destructiva. Índices únicos impiden versiones duplicadas y más de
una revisión vigente. `base_version_id` es un compare-and-set: publicaciones
basadas en una revisión obsoleta reciben `409`.

Las rutas `GET /api/v1/prompts/{sport}/{prompt_type}` y
`GET /api/v1/prompts/{sport}/{prompt_type}/versions` consultan la vigente y el
historial. El `POST` al recurso crea la primera versión o publica la siguiente.
La primera publicación debe enviar `base_version_id: null`; las siguientes,
el `version_id` vigente exacto.

### Zonas horarias

Todo se guarda en UTC. Al leer desde Mongo, el repositorio añade `UTC` a los
`datetime` naive antes de validarlos con Pydantic. `match.date` se expresa en
CDMX porque es la jornada que consulta el analista.

## Consulta

Los endpoints `/{sport}/results` leen directamente de MongoDB:

- `GET /api/v1/football/results`
- `GET /api/v1/nba/results`
- `GET /api/v1/baseball/results`
- `GET /api/v1/tennis/results`

Los pronósticos versionados se consultan con
`GET /api/v1/football/predictions` (filtros por jornada, rango, recepción, liga,
evento, analista, mercado, estado, periodo y timing).

Filtros disponibles: fecha, liga o circuito, hora de inicio, mercado y
probabilidad mínima.

## Paginación

Los headers de respuesta son:

```text
X-Total-Count    # total de registros que cumplen el filtro
X-Page           # página actual (base 1)
X-Page-Size      # tamaño de página aplicado
X-Total-Pages    # total de páginas
```

Si MongoDB no está configurado, estas rutas responden `503`.

## Liquidación

En la colección heredada, la liquidación compara el registro con el resultado
oficial y guarda el resultado de cada mercado:

| Estado | Unidades |
| --- | --- |
| `won` | `+100` |
| `lost` | `-100` |
| `push` | `0` |
| Sin finalizar | pendiente |

La liquidación de béisbol puede ejecutarse manualmente con
`POST /api/v1/baseball/results/settle` o automáticamente cada
`BASEBALL_SETTLEMENT_INTERVAL_SECONDS` segundos. `results/update` es el camino
general para fútbol, NBA, béisbol y tenis.

## Mercados

| Deporte | Forma de `markets` | Claves |
| --- | --- | --- |
| Fútbol | Anidada | `handicap`, `double_chance`, `goals`, `corners`, `cards`. |
| NBA y béisbol | Plana | `handicap_team`, `handicap_line`, `total_pick`, `total_line`. |
| Tenis | Anidada | `winner`, `set_handicap`, `total_games`. |

Si `markets` se omite, solo se liquida el ganador a partir de `pick`
(`prediction.predicted_result`). Las formas exactas y ejemplos están en la
[guía del analista](ANALISTA.md#mercados-opcionales).

`odds` y `stake` se guardan como información: las unidades liquidadas se
calculan con el resultado, no con la cuota.

## Documentos relacionados

- [Guía del analista](ANALISTA.md)
- [Endpoints](ENDPOINTS.md)
- [Configuración](CONFIGURACION.md)
