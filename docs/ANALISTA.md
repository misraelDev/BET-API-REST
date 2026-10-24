# Guía del analista

Esta guía es la base de trabajo para registrar apuestas en la API. Ya no hay
predicciones automáticas: **el pick lo decides tú** y la API solo guarda,
consulta y liquida.

Hay dos caminos de registro y conviven sin migrar datos:

| Camino | Para qué | Endpoints |
| --- | --- | --- |
| Registro manual simple | Un pick por partido en cualquier deporte. | `POST /api/v1/records` y `GET /api/v1/{sport}/results`. |
| Pronósticos de fútbol versionados | Varias selecciones por partido, historial de versiones, 22 mercados y liquidación por mercado. | `/api/v1/football/predictions/*`. |

## Qué cambió

| Antes | Ahora |
| --- | --- |
| `GET/POST /api/v1/{sport}/predictions` calculaba probabilidades y guardaba. | Esas rutas automáticas ya no existen. En fútbol hay un contrato nuevo de pronósticos versionados (`/api/v1/football/predictions`) donde tú envías la probabilidad. |
| El `event_id` lo obtenía el modelo desde la fuente. | Lo copias tú de la fuente oficial (salvo béisbol, que se deriva). |
| El modelo llenaba probabilidades, mercados y pesos. | Solo se guarda lo que envíes: selección, probabilidad, confianza, justificación y fuentes. |

La API **no** calcula probabilidades, no consulta cuotas y no tiene un endpoint
de calendario. Los partidos y sus identificadores se buscan en las fuentes
públicas que se describen abajo.

## Flujo de trabajo

### Registro simple (cualquier deporte)

1. Busca el partido en la fuente del deporte y anota su `event_id`.
2. Registra el pick con `POST /api/v1/records`.
3. Al terminar el partido, ejecuta `POST /api/v1/{sport}/results/update`.
4. Consulta lo guardado y la liquidación con `GET /api/v1/{sport}/results`.

El paso 3 y 4 usan el `event_id` como llave, por eso es importante copiarlo
bien.

### Pronósticos de fútbol versionados

1. Busca el partido en ESPN y anota su `event_id`.
2. Envía un lote de selecciones a `POST /api/v1/football/predictions`.
3. Tras el partido, ejecuta `POST /api/v1/football/results/update`.
4. Consulta con `GET /api/v1/football/predictions` y el detalle de cada
   selección con `GET /api/v1/football/predictions/{prediction_id}`.
5. Registra el diagnóstico posterior en
   `POST /api/v1/football/predictions/{prediction_id}/evaluations`.

El contrato completo se describe en
[Pronósticos de fútbol versionados](#pronósticos-de-fútbol-versionados).

## Cómo obtener el `event_id`

### Fútbol — Liga MX (id `4350`)

Fuente: TheSportsDB, la misma que usa la API internamente (clave pública
`123`).

```text
https://www.thesportsdb.com/api/v1/json/123/eventsseason.php?id=4350&s=2025-2026
```

- `s` es la temporada: `2025-2026` para Liga MX (agosto–mayo).
- En la respuesta, cada partido trae `idEvent`. **Ese número es el
  `event_id`.**
- También puedes ver el partido en
  `https://www.thesportsdb.com/event/<idEvent>`.

### Fútbol — Brasileirão (id `4351`)

```text
https://www.thesportsdb.com/api/v1/json/123/eventsseason.php?id=4351&s=2025
```

- `s` es el año natural (`2025`, `2026`...).
- Igual que Liga MX: el campo `idEvent` es el `event_id`.

Para partidos próximos de cualquiera de las dos ligas:

```text
https://www.thesportsdb.com/api/v1/json/123/eventsnextleague.php?id=4350
https://www.thesportsdb.com/api/v1/json/123/eventsnextleague.php?id=4351
```

### Fútbol — Leagues Cup

Fuente: ESPN. El `event_id` es el `id` del evento (coincide con
`competitions[0].id`).

```text
https://site.api.espn.com/apis/site/v2/sports/soccer/concacaf.leagues.cup/scoreboard?dates=20250801
```

`dates` va como `AAAAMMDD`.

### NBA, WNBA y Summer League

Fuente: ESPN. El `event_id` es `events[].id`.

```text
https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20250115
https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates=20250615
https://site.api.espn.com/apis/site/v2/sports/basketball/nba-summer-las-vegas/scoreboard?dates=20250715
```

Otros slugs de Summer League que consulta la API:
`nba-summer-california`, `nba-summer-golden-state`, `nba-summer-orlando`,
`nba-summer-sacramento`, `nba-summer-utah`.

### Tenis — ATP y WTA

Fuente: ESPN. El `event_id` es **`competitions[].id`** dentro de
`groupings[]`, no el id del torneo (`events[].id`, que se ve como `188-2025`).

```text
https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard?dates=20250701
https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard?dates=20250701
```

Ruta dentro del JSON:

```text
events[] → groupings[] (grouping.slug = mens-singles o womens-singles)
         → competitions[].id            ← event_id
         → competitions[].competitors[] → id y athlete.displayName
```

- `home_team` / `player_one` es el competidor con `order` menor.
- Guarda `home_team_id` y `away_team_id` con esos `id` si vas a apostar el
  handicap por sets.

### Béisbol — MLB y KBO

Aquí **no hay id oficial** en las fuentes públicas que usa la API: el
identificador es sintético. Lo más seguro es **no enviar `event_id`** y dejar
que la API lo derive con la fórmula interna:

```text
crc32("LIGA:game:AAAA-MM-DD:visitante:local") & 0x7FFFFFFF
```

- `LIGA` es `MLB` o `KBO`, en mayúsculas.
- Los nombres deben ser los canónicos de la fuente. En MLB la API traduce
  alias y abreviaturas (`NYY`, `Yankees`...) a nombres completos
  (`New York Yankees`). Usa el nombre completo para evitar dudas.
- Si envías un `event_id` inventado, `POST /baseball/results/settle` no
  encontrará el juego. `POST /baseball/results/update` sí funciona sin id,
  porque empareja por nombres de equipos y fecha.

## Registrar un pick

```text
POST /api/v1/records
Content-Type: application/json
```

### Campos

| Campo | Obligatorio | Descripción |
| --- | --- | --- |
| `sport` | Sí | `football`, `nba`, `baseball` o `tennis`. |
| `date` | Sí | Fecha del partido, `AAAA-MM-DD`. |
| `league` | Sí | Liga canónica (ver tabla abajo). |
| `event_id` | Sí salvo béisbol | Id del partido en su fuente. |
| `home_team` | Sí | Local. En tenis, jugador uno. |
| `away_team` | Sí | Visitante. En tenis, jugador dos. |
| `pick` | Sí | `home`, `draw` o `away`. `draw` solo en fútbol. En tenis, `home` = jugador uno. |
| `kickoff` | No | ISO-8601 con offset, por ejemplo `2026-08-01T19:00:00-06:00`. Si se omite: `00:00:00-06:00` del día. |
| `timezone` | No | Informativo. Por defecto `America/Mexico_City`. |
| `probability` | No | Tu probabilidad del pick, 0–100. Alimenta `min_probability`. |
| `odds` | No | Cuota decimal (> 1). Solo informativa, no se liquida. |
| `stake` | No | Unidades. Solo informativa. |
| `tournament` | No | Torneo de tenis. |
| `home_team_id` / `away_team_id` | No | Ids del local/visitante o de los jugadores. Mejoran la liquidación del handicap. |
| `markets` | No | Mercados adicionales (ver más abajo). |
| `notes` | No | Nota libre. |

### Ligas válidas

| `sport` | Valores aceptados (sin distinguir mayúsculas) |
| --- | --- |
| `football` | `Liga MX`, `Brasileirão Betano`, `Leagues Cup` |
| `nba` | `NBA`, `WNBA`, `NBA - Summer League` |
| `baseball` | `MLB`, `KBO` |
| `tennis` | `ATP`, `WTA` |

También se aceptan las formas cortas `liga_mx`, `brasileirao`, `leagues_cup`,
`summer_league`, `mlb`, `kbo`, `atp` y `wta`. La API guarda el nombre
canónico, que es el que usan los filtros `league` de `/results`.

### Ejemplo: fútbol

```powershell
$body = @{
  sport       = "football"
  date        = "2026-08-01"
  league      = "Liga MX"
  event_id    = 2266920
  home_team   = "Puebla"
  away_team   = "Atlas"
  pick        = "home"
  probability = 46
  odds        = 2.15
  stake       = 1
  kickoff     = "2026-08-01T19:00:00-06:00"
  notes       = "Local con descanso completo"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/records `
  -ContentType application/json `
  -Body $body
```

### Ejemplo: NBA

```powershell
$body = @{
  sport       = "nba"
  date        = "2026-01-15"
  league      = "NBA"
  event_id    = 401705127
  home_team   = "Philadelphia 76ers"
  away_team   = "New York Knicks"
  pick        = "away"
  probability = 55
  odds        = 1.90
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/records `
  -ContentType application/json `
  -Body $body
```

### Ejemplo: béisbol (sin `event_id`)

```powershell
$body = @{
  sport     = "baseball"
  date      = "2026-08-01"
  league    = "MLB"
  home_team = "New York Yankees"
  away_team = "Boston Red Sox"
  pick      = "home"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/records `
  -ContentType application/json `
  -Body $body
```

### Ejemplo: tenis

```powershell
$body = @{
  sport        = "tennis"
  date         = "2026-07-01"
  league       = "ATP"
  event_id     = 160455
  home_team    = "Alexander Blockx"
  away_team    = "Facundo Mena"
  home_team_id = 11757
  away_team_id = 2840
  pick         = "home"
  tournament   = "Wimbledon"
  markets      = @{
    winner = @{
      available  = $true
      selection  = "Alexander Blockx"
      probability = 62
    }
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/records `
  -ContentType application/json `
  -Body $body
```

### Respuesta

`201 Created` con el documento guardado (abreviado):

```json
{
  "document_id": "665f1c...",
  "sport": "football",
  "event_id": 2266920,
  "requested_date": "2026-08-01",
  "model_version": "manual-v1",
  "provider": "manual",
  "timezone": "America/Mexico_City",
  "prediction": {
    "fixture_id": 2266920,
    "league": "Liga MX",
    "home_team": "Puebla",
    "away_team": "Atlas",
    "probabilities": { "home": 46.0, "draw": 0.0, "away": 0.0 },
    "predicted_result": "home",
    "odds": 2.15,
    "stake": 1.0,
    "source": "manual",
    "markets": null
  },
  "settlement": null
}
```

Registrar dos veces el mismo partido con `manual-v1` **actualiza** el
documento; no crea duplicados. La llave es
`sport + event_id + fecha + model_version` (en tenis, sin `model_version`).

## Mercados opcionales

Si no envías `markets`, solo se liquida el ganador (`pick`). El formato depende
del deporte.

### Fútbol

```json
{
  "handicap":      { "available": true, "selection": "Puebla", "line": -0.5 },
  "double_chance": { "available": true, "selection": "Puebla o empate" },
  "goals":         { "available": true, "selection": "Más", "line": 2.5 },
  "corners":       { "available": true, "selection": "Más", "line": 9.5 },
  "cards":         { "available": true, "selection": "Menos", "line": 4.5 }
}
```

- `goals`, `corners` y `cards` usan `"Más"` / `"Menos"`.
- `line` es el hándicap o la línea total.
- Opcionalmente añade `probability` (0–100) en cada mercado para que
  `GET /results?market=handicap&min_probability=` pueda filtrarlos.

### NBA y béisbol

```json
{
  "handicap_team": "Philadelphia 76ers",
  "handicap_line": -4.5,
  "total_pick": "over",
  "total_line": 214.5
}
```

- `total_pick` es `over` o `under`.
- `handicap_team` debe coincidir con `home_team` o `away_team`.
- El filtro `min_probability` solo es fiable con `market=winner`; los demás
  mercados usan campos de confianza (`handicap_confidence`,
  `total_confidence`) que el registro manual no rellena.

### Tenis

```json
{
  "winner":      { "available": true, "selection": "Alexander Blockx" },
  "set_handicap": { "available": true, "selection": "Alexander Blockx", "line": -1.5 },
  "total_games": { "available": true, "selection": "Más", "line": 22.5 }
}
```

- `set_handicap` requiere `home_team_id` / `away_team_id` para resolver los
  sets de cada jugador.
- `total_games` usa `"Más"` / `"Menos"`.

## Consultar y liquidar

| Método | Ruta | Para qué |
| --- | --- | --- |
| GET | `/api/v1/football/results` | Registros de fútbol. |
| POST | `/api/v1/football/results/update` | Liquida con el resultado oficial. |
| GET | `/api/v1/nba/results` | Registros de NBA/WNBA. |
| POST | `/api/v1/nba/results/update` | Liquida NBA/WNBA/Summer League. |
| GET | `/api/v1/baseball/results` | Registros de béisbol. |
| POST | `/api/v1/baseball/results/update` | Liquida con resultados oficiales MLB/KBO. |
| POST | `/api/v1/baseball/results/settle` | Liquida con el calendario público MLB. |
| GET | `/api/v1/tennis/results` | Registros de tenis. |
| POST | `/api/v1/tennis/results/update` | Liquida ATP/WTA. |
| GET | `/api/v1/baseball/stats` | Dashboard de béisbol. |

```powershell
# Ver lo registrado
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/football/results?date=2026-08-01&league=liga_mx"

# Liquidar el día
$body = @{ date = "2026-08-01" } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/football/results/update `
  -ContentType application/json -Body $body
```

La liquidación se guarda en `settlement` dentro del mismo documento y no
sobrescribe tu pick ni tus probabilidades.

## Pronósticos de fútbol versionados

Este contrato guarda **una selección atómica** por mercado, periodo y línea.
Una petición puede incluir hasta 100 selecciones y cada una se guarda, versiona
y liquida por separado. Es el camino recomendado cuando necesitas recuperar
exactamente qué se registró, quién lo hizo, con qué probabilidad y si el
servidor lo recibió antes del inicio.

### Endpoints

| Método | Ruta | Para qué |
| --- | --- | --- |
| GET | `/api/v1/football/predictions/markets` | Catálogo de ligas, mercados, periodos, estados y reglas. |
| POST | `/api/v1/football/predictions` | Registra un lote de selecciones. |
| GET | `/api/v1/football/predictions` | Consulta el historial con filtros y paginación. |
| GET | `/api/v1/football/predictions/{prediction_id}` | Detalle con todas las versiones. |
| POST | `/api/v1/football/predictions/{prediction_id}/evaluations` | Diagnóstico posterior del analista. |
| GET | `/api/v1/football/predictions/{prediction_id}/evaluations` | Evaluaciones posteriores registradas. |

### Identificadores y versiones

| Campo | Quién lo genera | Regla |
| --- | --- | --- |
| `prediction_id` | Tú o el servidor | Identificador estable de la selección. Si lo omites, el servidor crea uno. Reenviarlo crea una **versión nueva**, nunca sobrescribe. |
| `version` | Servidor | Entero consecutivo que empieza en 1. |
| `version_id` | Servidor | Identificador único de esa versión concreta; es lo que se liquida y evalúa. |
| `idempotency_key` | Tú | Clave única del envío. El mismo cuerpo con la misma clave devuelve la versión existente; un cuerpo distinto se rechaza como conflicto. |
| `request_hash` | Servidor | Huella del cuerpo para comparar reintentos. |

Al crear una versión nueva deben permanecer idénticos `event_id`, `market`,
`period` y la identidad de la selección (`selection`, `line`, `team`, `player`,
`player_id`, `home_goals`, `away_goals`). Lo que puede cambiar es la
probabilidad, la confianza, la justificación, las fuentes y el resto del
contexto. La versión anterior se conserva con `is_current=false` y la nueva
apunta a ella con `supersedes_version_id`.

La respuesta del lote trae `received_at`, `total`, `created`, `replayed`,
`rejected` y un resultado por elemento. El código HTTP resume el lote:

| Código | Cuándo |
| --- | --- |
| `201` | Se creó al menos una versión nueva. |
| `200` | Todas las selecciones eran reintentos idempotentes. |
| `409` | Ninguna selección se pudo aceptar (conflicto de clave o de identidad). |
| `422` | El cuerpo completo no cumple el esquema o el mercado no admite el periodo. |

### Campos de cada selección

| Campo | Obligatorio | Descripción |
| --- | --- | --- |
| `idempotency_key` | Sí | 8–128 caracteres `A-Z a-z 0-9 . _ : -`. Única dentro de la petición y en la base. |
| `event_id` | Sí | Id del partido en ESPN. |
| `match_date` | Sí | Jornada declarada en CDMX (`AAAA-MM-DD`). El servidor guarda en `match.date` la fecha derivada del `kickoff` conocido y conserva la declarada en `match.declared_date`. |
| `league` | Sí | Código de liga del catálogo (`liga_mx`, `premier_league`...). |
| `home_team` / `away_team` | Sí | Nombres como los reporta ESPN. |
| `market` | Sí | Código de mercado (ver tabla). |
| `period` | No | `full_time` por defecto, `first_half` o `second_half`. |
| `selection` | Según mercado | Valor permitido por el mercado. |
| `line` | Según mercado | Múltiplo de 0.5, nunca 0. En over/under debe ser ≥ 0.5. En hándicaps se admite negativa y se suma al equipo elegido. |
| `team` | Según mercado | `home` o `away` para mercados por equipo. |
| `player` / `player_id` | Según mercado | Jugador para mercados individuales. `player_id` mejora la identificación. |
| `home_goals` / `away_goals` | Marcador exacto | Goles declarados para `exact_score`. |
| `probability` | Sí | 0–100. |
| `confidence` | Sí | Entero 1–5. |
| `rationale` | Sí | Justificación, 5–4000 caracteres. |
| `sources` | Sí | Una o más fuentes con `name`, `url` opcional y `note` opcional. |
| `analyst` | Sí | Identificador del analista. |
| `method_version` | Sí | Versión del método usado. |
| `kickoff` | Recomendado | ISO-8601 con offset. Se verifica contra ESPN; si no se puede, se usa como referencia y queda `kickoff_verified=false`. |
| `generated_at` | No | Hora declarada de generación, con offset. Se guarda aparte y **nunca** sustituye a `received_at`. |
| `prediction_id` | No | Para versionar una selección existente. |
| `notes` | No | Nota libre. |

Todas las fechas se guardan en UTC. `received_at` lo genera el servidor y es la
prueba de cuándo llegó la selección.

### Ligas del catálogo

| Código | Competición | País/región |
| --- | --- | --- |
| `liga_mx` | Liga MX | México |
| `liga_expansion_mx` | Liga de Expansión MX | México |
| `brasileirao` | Brasileirão Betano | Brasil |
| `leagues_cup` | Leagues Cup | Norteamérica |
| `mls` | MLS | Estados Unidos |
| `la_liga` | LaLiga | España |
| `premier_league` | Premier League | Inglaterra |
| `serie_a` | Serie A | Italia |
| `bundesliga` | Bundesliga | Alemania |
| `ligue_1` | Ligue 1 | Francia |
| `champions_league` | UEFA Champions League | Europa |
| `europa_league` | UEFA Europa League | Europa |
| `libertadores` | CONMEBOL Libertadores | Sudamérica |
| `sudamericana` | CONMEBOL Sudamericana | Sudamérica |
| `liga_betplay` | Liga BetPlay | Colombia |
| `liga_profesional_argentina` | Liga Profesional Argentina | Argentina |
| `primera_division_chile` | Primera División de Chile | Chile |
| `liga_1_peru` | Liga 1 | Perú |
| `ligapro_ecuador` | LigaPro | Ecuador |
| `primera_division_uruguay` | Primera División de Uruguay | Uruguay |

`GET /predictions/markets` devuelve esta lista con el slug de ESPN de cada liga.

### Mercados y periodos

`FT` = `full_time`, `1T` = `first_half`, `2T` = `second_half`. El segundo
tiempo **no acumula** el primero.

| Mercado | Selección | Extras | Periodos |
| --- | --- | --- | --- |
| `1x2` | `home`, `draw`, `away` | — | FT, 1T, 2T |
| `double_chance` | `home_or_draw`, `home_or_away`, `draw_or_away` | — | FT, 1T, 2T |
| `asian_handicap` | `home`, `away` | `line` | FT, 1T, 2T |
| `european_handicap` | `home`, `away` | `line` | FT, 1T, 2T |
| `total_goals` | `over`, `under` | `line` | FT, 1T, 2T |
| `team_total_goals` | `over`, `under` | `line`, `team` | FT, 1T, 2T |
| `btts` | `yes`, `no` | — | FT, 1T, 2T |
| `corners_total` | `over`, `under` | `line` | FT |
| `corners_team` | `over`, `under` | `line`, `team` | FT |
| `corners_handicap` | `home`, `away` | `line` | FT |
| `corners_most` | `home`, `draw`, `away` | — | FT |
| `cards_total` | `over`, `under` | `line` | FT, 1T, 2T |
| `cards_team` | `over`, `under` | `line`, `team` | FT, 1T, 2T |
| `cards_player` | `over`, `under` | `line`, `player` | FT, 1T, 2T |
| `exact_score` | — | `home_goals` y `away_goals` | FT, 1T, 2T |
| `first_team_to_score` | `home`, `away`, `none` | — | FT, 1T, 2T |
| `shots_total` | `over`, `under` | `line` | FT |
| `shots_team` | `over`, `under` | `line`, `team` | FT |
| `shots_player` | `over`, `under` | `line`, `player` | FT |
| `shots_on_target_total` | `over`, `under` | `line` | FT |
| `shots_on_target_team` | `over`, `under` | `line`, `team` | FT |
| `shots_on_target_player` | `over`, `under` | `line`, `player` | FT |

Córners, remates y remates a puerta solo admiten tiempo completo porque las
fuentes no los separan por tiempo. Enviar otro periodo devuelve `422`.

Quedan **fuera** de esta entrega: asistencias, goleadores individuales y
porterías a cero.

### Momento del registro (timing)

| Estado | Significado |
| --- | --- |
| `pre_match` | `received_at` es anterior al inicio verificado o declarado. |
| `late` | Llegó después del inicio. Se acepta, pero no cuenta como pre-partido. |
| `unverified` | No hay ningún `kickoff` (ni de ESPN ni declarado); el servidor no puede afirmar si llegó antes. |

`POST` no rechaza registros tardíos: los guarda con `timing.status=late` y
`received_before_kickoff=false` para que puedas excluirlos de cualquier análisis
pre-partido. Un `generated_at` manual nunca convierte un registro tardío en
pre-partido.

`match.kickoff_verified=true` solo cuando ESPN confirmó el inicio. Si únicamente
existe el `kickoff` que declaraste, el estado se calcula contra esa hora y queda
`kickoff_verified=false`: sirve para ordenar, pero no es prueba de la hora real.
Si no hay ninguna de las dos, el estado es `unverified` y
`received_before_kickoff` es `null`.

### Liquidación

`POST /api/v1/football/results/update` liquida las versiones vigentes del día.
Cada selección guarda `settlement_status` y un objeto `settlement` con
`observed`, `summary`, `reason`, `source`, `settled_at` y `rule_version`
(`football-settlement-v1`).

| Estado | Significado |
| --- | --- |
| `pendiente` | El partido no terminó o falta información. |
| `acertado` | La selección coincidió con el resultado observado. |
| `fallado` | No coincidió. |
| `reembolso` | Empate en la línea o en el mercado (push). |
| `anulado` | Partido cancelado o abandonado. |
| `no_evaluable` | La fuente no permite verificar el mercado o el periodo. |

Reglas que conviene tener presentes:

- **1X2 y doble oportunidad** comparan el marcador del periodo.
- **Hándicap asiático**: la línea se suma al equipo elegido. Margen ajustado
  cero es `reembolso`.
- **Hándicap europeo**: el empate ajustado es `fallado`, no `reembolso`.
- **Over/under**: total igual a la línea entera es `reembolso`; con línea .5
  siempre hay ganador.
- **Córners**: solo tiempo completo. «Más córners» empatado es `reembolso`. El
  hándicap de córners suma la línea a los córners del equipo elegido.
- **Tarjetas**: cada tarjeta mostrada cuenta 1. Una segunda amarilla cuenta
  amarilla + roja (2) cuando la fuente la reporta; una roja directa cuenta 1. El
  total es amarillas + rojas. La fuente preferida son los eventos del partido.
- **Primer equipo en anotar**: se ordenan los goles por tiempo; `none` gana si
  no hubo goles. Un autogol se acredita al equipo contrario al que reporta la
  fuente.
- **Remates**: se usa `totalShots` de ESPN; los bloqueados se publican aparte y
  no se suman. **Remates a puerta** usa `shotsOnTarget`.
- **Jugadores**: si no participaron y la plantilla está disponible, su total es
  0. Si no hay datos verificables, el estado es `no_evaluable`; nunca se infiere
  un acierto o un fallo.
- **Alargue y penales**: el marcador de `full_time` es la regulación (primeros
  dos parciales), sin alargue ni penales. En partidos con alargue, córners y
  remates quedan `no_evaluable` porque las estadísticas incluyen el tiempo
  extra; las tarjetas se cuentan con los eventos.

La liquidación oficial es responsabilidad del servicio autorizado. La
evaluación del analista no la sustituye ni la modifica.

### Evaluación posterior

`POST /api/v1/football/predictions/{prediction_id}/evaluations` guarda el
diagnóstico en otra colección y lo liga a `prediction_id`, `version` y
`version_id`.

| Campo | Obligatorio | Descripción |
| --- | --- | --- |
| `analyst` | Sí | Analista que evalúa. |
| `diagnosis` | Sí | Qué pasó y por qué, mínimo 10 caracteres. |
| `learnings` | Sí | Lista de aprendizajes accionables. |
| `sources` | Sí | Fuentes usadas en la evaluación. |
| `version` | No | Versión evaluada; por defecto, la vigente. |
| `outcome_comment` | No | Comentario sobre el resultado observado. |
| `tags` | No | Etiquetas para agrupar aprendizajes. |

La evaluación **no** puede cambiar la selección, la probabilidad, la confianza
ni la fecha original. Un mismo analista solo puede evaluar una vez cada versión;
el segundo intento devuelve `409`.

### Ejemplo de lote

```powershell
$body = @{
  items = @(
    @{
      idempotency_key = "2026-10-24-liga-mx-736644-1x2-home"
      event_id        = 736644
      match_date      = "2026-10-24"
      league          = "liga_mx"
      home_team       = "Pumas UNAM"
      away_team       = "Necaxa"
      kickoff         = "2026-10-24T20:00:00-06:00"
      market          = "1x2"
      period          = "full_time"
      selection       = "home"
      probability     = 58
      confidence      = 4
      rationale       = "Local con mejor forma y ventaja de localía."
      sources         = @(@{ name = "ESPN"; url = "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/summary?event=736644" })
      analyst         = "ana.garcia"
      method_version  = "analista-v1"
    },
    @{
      idempotency_key = "2026-10-24-liga-mx-736644-total-goals-over"
      event_id        = 736644
      match_date      = "2026-10-24"
      league          = "liga_mx"
      home_team       = "Pumas UNAM"
      away_team       = "Necaxa"
      kickoff         = "2026-10-24T20:00:00-06:00"
      market          = "total_goals"
      period          = "full_time"
      selection       = "over"
      line            = 2.5
      probability     = 61
      confidence      = 3
      rationale       = "Ambos equipos generan más de dos goles por partido."
      sources         = @(@{ name = "ESPN" })
      analyst         = "ana.garcia"
      method_version  = "analista-v1"
    }
  )
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/football/predictions `
  -ContentType application/json `
  -Body $body
```

La respuesta (abreviada):

```json
{
  "received_at": "2026-10-24T17:05:12.345678Z",
  "total": 2,
  "created": 2,
  "replayed": 0,
  "rejected": 0,
  "items": [
    {
      "prediction_id": "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8",
      "version": 1,
      "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
      "idempotency_key": "2026-10-24-liga-mx-736644-1x2-home",
      "status": "created",
      "error": null,
      "analyst": "ana.garcia",
      "probability": 58.0,
      "received_before_kickoff": true
    }
  ]
}
```

### Consulta, filtros y paginación

`GET /api/v1/football/predictions` devuelve `items`, `page`, `page_size` y
`total`. Por defecto solo muestra la versión vigente de cada selección.

| Parámetro | Descripción |
| --- | --- |
| `match_date` | Jornada exacta en CDMX. |
| `match_date_from` / `match_date_to` | Rango de jornadas. No se combina con `match_date`. |
| `received_date` | Día en que el servidor recibió el registro, en CDMX. |
| `league` | Código de liga. |
| `event_id` | Partido. |
| `analyst` | Analista exacto. |
| `market` | Código de mercado. |
| `settlement_status` | `pendiente`, `acertado`, `fallado`, `reembolso`, `anulado` o `no_evaluable`. |
| `period` | `full_time`, `first_half` o `second_half`. |
| `timing` | `pre_match`, `late` o `unverified`. |
| `include_versions` | `true` incluye versiones anteriores. |
| `page` / `page_size` | Paginación; por defecto 1 y 50, máximo 200. |

La respuesta incluye los headers `X-Total-Count`, `X-Page`, `X-Page-Size` y
`X-Total-Pages`.

Para recuperar una selección concreta usa el detalle por `prediction_id`:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/football/predictions/3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8"
```

Devuelve `prediction_id`, `total_versions`, `current_version` y `versions` en
orden ascendente.

### Ver el catálogo de mercados

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/football/predictions/markets"
```

Incluye la versión de reglas (`football-settlement-v1`), los periodos, los
estados de liquidación con su significado, las 20 ligas y los 22 mercados con
`requires_line`, `requires_team`, `requires_player`, `requires_score` y la regla
de liquidación en texto.

## Errores frecuentes

| Código | Causa habitual |
| --- | --- |
| `422` | Liga no válida, `event_id` ausente fuera de béisbol, `draw` en un deporte que no es fútbol, `odds <= 1` o `probability` fuera de 0–100. En pronósticos de fútbol también: mercado incompatible con el periodo, `line` que no es múltiplo de 0.5, falta `team`/`player`/`line` o una fecha sin offset. |
| `409` | En pronósticos de fútbol: `idempotency_key` repetida con cuerpo distinto o versión nueva que cambia la identidad de la selección. En evaluaciones: ese analista ya evaluó esa versión. |
| `404` | `prediction_id` o versión inexistente en pronósticos de fútbol. |
| `503` | MongoDB no está disponible. |
| `502` | La fuente externa falló al liquidar. |

Otros puntos a tener en cuenta:

- `odds` y `stake` son informativos. Las unidades liquidadas se calculan con
  el resultado, no con tu cuota.
- El filtro `hour` de `/results` interpreta la hora en horario de México
  (UTC-6). Envía `kickoff` con offset `-06:00` para que coincida.
- En béisbol, `POST /baseball/results/settle` solo cubre MLB. KBO se liquida
  con `/results/update`.
- En tenis, la liquidación del ganador compara el nombre exacto del jugador con
  el que devuelve ESPN.
- No hay endpoint de calendario: las fuentes de esta guía son la referencia.

## Documentos relacionados

- [Endpoints](ENDPOINTS.md)
- [Ejemplos](EJEMPLOS.md)
- [Persistencia](PERSISTENCIA.md)
- [Limitaciones](LIMITACIONES.md)
