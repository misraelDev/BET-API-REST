# Endpoints

Base URL local: `http://127.0.0.1:8000`. Todos los cuerpos y respuestas usan
`application/json`. No hay autenticación.

La API **no genera predicciones**. El registro es manual y se hace con
`POST /api/v1/records` (un pick simple) o, en fútbol, con
`POST /api/v1/football/predictions` (lote versionado de selecciones). Además,
`/api/v1/prompts` administra prompts versionados de análisis y evaluación para
los cuatro deportes.

## Sistema

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/health` | Estado del servicio y de la conexión a MongoDB. |
| GET | `/api/v1/sports` | Catálogo de deportes, fuente y versión (`manual-v1`). |
| POST | `/api/v1/records` | Registra un partido con tu pick. |

Cuerpo de `POST /api/v1/records`: `sport`, `date`, `league`, `home_team`,
`away_team`, `pick` y, salvo en béisbol, `event_id`. Opcionales: `kickoff`,
`timezone`, `probability`, `odds`, `stake`, `tournament`, `home_team_id`,
`away_team_id`, `markets` y `notes`.

Detalle de campos, fuentes de `event_id` y ejemplos por deporte:
[Guía del analista](ANALISTA.md).

## Fútbol

### Resultados del registro manual

| Método | Ruta | Parámetros | Cuerpo |
| --- | --- | --- | --- |
| GET | `/api/v1/football/results` | `date`, `league`, `page`, `page_size`, `hour`, `market`, `min_probability`, `limit` (obsoleto) | — |
| POST | `/api/v1/football/results/update` | — | `{ "date": "YYYY-MM-DD" }` |

Ligas para `GET`: `all`, `liga_mx`, `brasileirao`, `leagues_cup`. En el registro
usa los nombres canónicos `Liga MX`, `Brasileirão Betano` y `Leagues Cup`.
`/results` sigue siendo el endpoint heredado y no cambia.

`POST /results/update` liquida dos colecciones a la vez:

- La colección heredada (`MONGODB_COLLECTION`), con los contadores
  `predictions_matched` y `predictions_updated`.
- La colección de pronósticos versionados, con
  `football_predictions_matched`, `football_predictions_settled`,
  `football_predictions_updated` y `football_predictions_pending`.

La respuesta incluye además `source` (fuentes consultadas),
`unmatched_event_ids` (partidos con pronósticos que la fuente no devolvió),
`fixtures_without_predictions` (partidos finalizados sin pronóstico) y `errors`
con `event_id`, `stage` y `message`.

### Pronósticos versionados

| Método | Ruta | Parámetros | Cuerpo |
| --- | --- | --- | --- |
| GET | `/api/v1/football/predictions/markets` | — | — |
| POST | `/api/v1/football/predictions` | — | `{ "items": [ ... ] }` (1–100 selecciones) |
| GET | `/api/v1/football/predictions` | ver tabla de filtros | — |
| GET | `/api/v1/football/predictions/{prediction_id}` | — | — |
| POST | `/api/v1/football/predictions/{prediction_id}/evaluations` | — | `version_id`, `analyst`, `diagnosis`, `learnings`, `sources`; opcionales `outcome_comment`, `tags` |
| GET | `/api/v1/football/predictions/{prediction_id}/evaluations` | `page`, `page_size` | — |

Filtros de `GET /api/v1/football/predictions`:

| Parámetro | Tipo | Descripción |
| --- | --- | --- |
| `match_date` | fecha | Jornada exacta en CDMX. Excluyente con el rango. |
| `match_date_from` / `match_date_to` | fecha | Rango de jornadas en CDMX. |
| `received_date` | fecha | Día de recepción del servidor, en CDMX. |
| `league` | código | Código de liga del catálogo (`liga_mx`, `premier_league`...). |
| `event_id` | entero | Partido. |
| `analyst` | texto | Analista exacto. |
| `market` | código | Mercado (`1x2`, `total_goals`, `cards_player`...). |
| `settlement_status` | enum | `pendiente`, `acertado`, `fallado`, `reembolso`, `anulado`, `no_evaluable`. |
| `period` | enum | `full_time`, `first_half`, `second_half`. |
| `timing` | enum | `pre_match`, `late`, `unverified`. |
| `include_versions` | booleano | Por defecto solo la versión vigente. |
| `page` | entero ≥ 1 | Página. |
| `page_size` | entero 1–200 | Por defecto 50. |

La lista devuelve `items`, `page`, `page_size` y `total`. El detalle devuelve
`prediction_id`, `total_versions`, `current_version` y `versions`.

Códigos de `POST /predictions`: `201` si se creó al menos una versión, `200` si
todo fueron reintentos idempotentes y `409` si todo se rechazó. Los detalles del
contrato están en la
[guía del analista](ANALISTA.md#pronósticos-de-fútbol-versionados).

## Básquetbol

| Método | Ruta | Parámetros | Cuerpo |
| --- | --- | --- | --- |
| GET | `/api/v1/nba/results` | `date`, `page`, `page_size`, `hour`, `league`, `market`, `min_probability` | — |
| POST | `/api/v1/nba/results/update` | — | `{ "date", "league" }` |

Ligas: `nba`, `wnba`, `summer_league`, `all`. Valor por defecto: `nba`.

## Béisbol

| Método | Ruta | Parámetros | Cuerpo |
| --- | --- | --- | --- |
| GET | `/api/v1/baseball/stats` | `league`, `days` | — |
| GET | `/api/v1/baseball/official-results` | `date` (req), `league` | — |
| GET | `/api/v1/baseball/results` | `date`, `league`, `page`, `page_size`, `hour`, `market`, `min_probability`, `limit` (obsoleto) | — |
| POST | `/api/v1/baseball/results/update` | — | `{ "date", "league" }` |
| POST | `/api/v1/baseball/results/settle` | `date` (req), `timezone`, `league` | — |

Ligas: `mlb`, `kbo`, `all`. Valor por defecto en `official-results`: `mlb`.

## Tenis

| Método | Ruta | Parámetros | Cuerpo |
| --- | --- | --- | --- |
| GET | `/api/v1/tennis/matches/count` | `date` (req), `timezone`, `tour` | — |
| GET | `/api/v1/tennis/results` | `date`, `tour`, `page`, `page_size`, `hour`, `market`, `min_probability`, `limit` (obsoleto) | — |
| POST | `/api/v1/tennis/results/update` | — | `{ "date", "tour" }` |

Circuitos: `atp`, `wta`, `all`.

## Prompts de analistas

| Método | Ruta | Parámetros/cuerpo | Descripción |
| --- | --- | --- | --- |
| GET | `/api/v1/prompts/{sport}/{prompt_type}` | Query opcional `version` o `version_id` | Vigente por defecto o revisión exacta. |
| GET | `/api/v1/prompts/{sport}/{prompt_type}/versions` | — | Historial inmutable, ascendente. |
| POST | `/api/v1/prompts/{sport}/{prompt_type}` | `base_version_id`, `prompt`, `author`, `change_summary` | Publica una nueva versión; no sobrescribe. |

`sport`: `football`, `nba`, `baseball` o `tennis`. `prompt_type`: `analysis` o
`evaluation`. Para la primera publicación, `base_version_id` debe ser `null`;
para una mejora, usa el `version_id` actualmente vigente. Una base obsoleta
responde `409`. El endpoint no tiene autenticación: restríngele el acceso de
escritura desde la red o el proxy.

Más detalle: [API de prompts para analistas](PROMPTS_API.md).

## Parámetros comunes

| Parámetro | Tipo | Descripción |
| --- | --- | --- |
| `date` | fecha `YYYY-MM-DD` | Día de los partidos. Obligatorio en `matches/count` y `results/settle`. |
| `timezone` | texto | Zona horaria IANA. Por defecto `America/Mexico_City`. |
| `page` | entero ≥ 1 | Página solicitada. |
| `page_size` | entero 1–200 | Registros por página. Por defecto 50. |
| `hour` | entero 0–23 | Filtra por hora de inicio; requiere `date`. Se evalúa en UTC-6. |
| `market` | texto | `winner` (por defecto), `handicap` o `total`. En fútbol también `double_chance`, `goals`, `corners` y `cards`; en tenis `set_handicap`, `total_games` y `exact_sets`. |
| `min_probability` | número 0–100 | Probabilidad mínima para incluir el registro. |

## Paginación

Los `GET` de `/{sport}/results` y de `/football/predictions` devuelven estos
headers:

```text
X-Total-Count
X-Page
X-Page-Size
X-Total-Pages
```

## Errores

| Código | Significado |
| --- | --- |
| `404` | No existe el `prediction_id` o la versión solicitada. |
| `409` | Conflicto de idempotencia, de identidad de versión o evaluación duplicada. |
| `422` | Parámetro, liga, mercado, periodo o cuerpo inválido. |
| `502` | La fuente externa devolvió datos incompatibles o falló. |
| `503` | MongoDB no está disponible y la ruta lo requiere. |

## Documentos relacionados

- [Guía del analista](ANALISTA.md)
- [Ejemplos de petición](EJEMPLOS.md)
- [Persistencia](PERSISTENCIA.md)
- [Contrato OpenAPI](OPENAPI.md)
