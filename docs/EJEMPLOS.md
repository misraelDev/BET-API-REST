# Ejemplos de petición

Todos los ejemplos usan PowerShell y la API en `http://127.0.0.1:8000`.
Para preparar el registro (fuentes, `event_id` y mercados) consulta la
[guía del analista](ANALISTA.md).

## Registrar un partido de fútbol

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
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/records `
  -ContentType application/json `
  -Body $body
```

## Registrar un lote de pronósticos de fútbol

Cada elemento es una selección atómica. Aquí van dos mercados del mismo
partido:

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
      generated_at    = "2026-10-24T10:30:00-06:00"
    },
    @{
      idempotency_key = "2026-10-24-liga-mx-736644-cards-over"
      event_id        = 736644
      match_date      = "2026-10-24"
      league          = "liga_mx"
      home_team       = "Pumas UNAM"
      away_team       = "Necaxa"
      kickoff         = "2026-10-24T20:00:00-06:00"
      market          = "cards_total"
      period          = "full_time"
      selection       = "over"
      line            = 3.5
      probability     = 54
      confidence      = 3
      rationale       = "Dos equipos con promedio alto de faltas y tarjetas."
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

Reenviar el mismo cuerpo con la misma `idempotency_key` devuelve `200` y la
versión existente. Cambiar la probabilidad con la misma clave devuelve `409`.

## Versionar una selección

Envía el mismo `prediction_id` con una `idempotency_key` nueva. La identidad
(`event_id`, mercado, periodo, selección, línea, equipo, jugador y marcador) no
puede cambiar.

```powershell
$body = @{
  items = @(
    @{
      prediction_id   = "3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8"
      idempotency_key = "2026-10-24-liga-mx-736644-1x2-home-v2"
      event_id        = 736644
      match_date      = "2026-10-24"
      league          = "liga_mx"
      home_team       = "Pumas UNAM"
      away_team       = "Necaxa"
      kickoff         = "2026-10-24T20:00:00-06:00"
      market          = "1x2"
      period          = "full_time"
      selection       = "home"
      probability     = 63
      confidence      = 5
      rationale       = "Se confirma la alineación titular y el local mantiene la forma."
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

## Consultar pronósticos y versiones

```powershell
# Versiones vigentes de la jornada, solo registros recibidos antes del inicio
$r = Invoke-WebRequest `
  "http://127.0.0.1:8000/api/v1/football/predictions?match_date=2026-10-24&timing=pre_match&page=1&page_size=50"

$r.Headers["X-Total-Count"]
$r.Content | ConvertFrom-Json

# Historial completo, incluidas versiones anteriores
Invoke-RestMethod `
  "http://127.0.0.1:8000/api/v1/football/predictions?include_versions=true&analyst=ana.garcia"

# Detalle con todas las versiones de una selección
Invoke-RestMethod `
  "http://127.0.0.1:8000/api/v1/football/predictions/3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8"
```

## Ver el catálogo de mercados y reglas

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8000/api/v1/football/predictions/markets"
```

## Liquidar y evaluar el partido

```powershell
$body = @{ date = "2026-10-24" } | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/football/results/update `
  -ContentType application/json `
  -Body $body
```

La respuesta incluye los contadores heredados y los nuevos
(`football_predictions_matched`, `football_predictions_settled`,
`football_predictions_updated`, `football_predictions_pending`), además de
`unmatched_event_ids`, `fixtures_without_predictions` y `errors`.

Después del partido, registra el diagnóstico del analista:

```powershell
$body = @{
  analyst   = "ana.garcia"
  diagnosis = "El local dominó el primer tiempo y sentenció en el segundo."
  learnings = @("La ventaja de localía pesó más que la forma reciente.")
  sources   = @(@{ name = "ESPN" })
  tags      = @("1x2")
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/football/predictions/3d0f6f3e5c1a4f0ab1c2d3e4f5a6b7c8/evaluations `
  -ContentType application/json `
  -Body $body
```

## Registrar un partido de NBA

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
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/records `
  -ContentType application/json `
  -Body $body
```

## Registrar un partido de béisbol (sin `event_id`)

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

## Registrar un partido de tenis con mercados

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
    winner = @{ available = $true; selection = "Alexander Blockx"; probability = 62 }
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/records `
  -ContentType application/json `
  -Body $body
```

## Consultar resultados guardados con paginación

```powershell
$r = Invoke-WebRequest `
  "http://127.0.0.1:8000/api/v1/nba/results?date=2026-01-15&page=1&page_size=25"

$r.Headers["X-Total-Count"]
$r.Headers["X-Total-Pages"]
$r.Content | ConvertFrom-Json
```

## Filtrar por mercado y probabilidad

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8000/api/v1/football/results?date=2026-08-01&market=goals&min_probability=60"
```

## Actualizar resultados oficiales

```powershell
$body = @{ date = "2026-08-01"; league = "mlb" } | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/baseball/results/update `
  -ContentType application/json `
  -Body $body
```

## Liquidar béisbol desde el calendario público

```powershell
Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8000/api/v1/baseball/results/settle?date=2026-08-01&league=all"
```

## Estadísticas de béisbol

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8000/api/v1/baseball/stats?league=mlb&days=30"
```

## Equivalente con curl

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/records" \
  -H "Content-Type: application/json" \
  -d '{"sport":"football","date":"2026-08-01","league":"Liga MX","event_id":2266920,"home_team":"Puebla","away_team":"Atlas","pick":"home","probability":46}'
```

Para el lote versionado:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/football/predictions" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"idempotency_key":"2026-10-24-liga-mx-736644-1x2-home","event_id":736644,"match_date":"2026-10-24","league":"liga_mx","home_team":"Pumas UNAM","away_team":"Necaxa","market":"1x2","period":"full_time","selection":"home","probability":58,"confidence":4,"rationale":"Local con mejor forma.","sources":[{"name":"ESPN"}],"analyst":"ana.garcia","method_version":"analista-v1"}]}'
```

## Documentos relacionados

- [Guía del analista](ANALISTA.md)
- [Endpoints](ENDPOINTS.md)
- [Persistencia](PERSISTENCIA.md)
