# Configuración

Todas las variables se leen del archivo `.env` en la raíz del proyecto. Toma
como base `.env.example` y ajusta los valores.

## Proveedores de fútbol

```dotenv
API_FOOTBALL_KEY=coloca_aqui_tu_api_key
API_FOOTBALL_BASE_URL=https://v3.football.api-sports.io
FOOTBALL_DATA_API_KEY=coloca_aqui_tu_token
FOOTBALL_DATA_BASE_URL=https://api.football-data.org/v4
API_NBA_BASE_URL=https://v2.nba.api-sports.io
```

Las claves vacías no impiden el arranque: la API cae a las fuentes públicas
disponibles.

## MongoDB

```dotenv
MONGODB_URI=mongodb://usuario:password@host:27017/?tls=false
MONGODB_DATABASE=sports_db
MONGODB_COLLECTION=predictions
MONGODB_FOOTBALL_PREDICTIONS_COLLECTION=football_predictions
MONGODB_FOOTBALL_EVALUATIONS_COLLECTION=football_prediction_evaluations
MONGODB_REQUIRED=false
```

| Variable | Descripción |
| --- | --- |
| `MONGODB_URI` | Cadena de conexión. Si está vacía, la persistencia queda deshabilitada. |
| `MONGODB_DATABASE` | Base de datos destino. |
| `MONGODB_COLLECTION` | Colección del registro manual (nombre heredado `predictions`). |
| `MONGODB_FOOTBALL_PREDICTIONS_COLLECTION` | Pronósticos de fútbol versionados. Por defecto `football_predictions`. |
| `MONGODB_FOOTBALL_EVALUATIONS_COLLECTION` | Evaluaciones posteriores del analista. Por defecto `football_prediction_evaluations`. |
| `MONGODB_REQUIRED` | Si es `true`, la aplicación no inicia cuando MongoDB no responde. |

Las credenciales se leen solo en el backend. No las expongas en el frontend ni
en los contratos OpenAPI.

## Pronósticos de fútbol

```dotenv
FOOTBALL_KICKOFF_LOOKUP_ENABLED=true
FOOTBALL_KICKOFF_TIMEOUT_SECONDS=8
PUBLIC_BASE_URL=
```

| Variable | Descripción |
| --- | --- |
| `FOOTBALL_KICKOFF_LOOKUP_ENABLED` | Consulta el inicio del partido en ESPN para verificar si el registro llegó antes. Si es `false`, se usa el `kickoff` declarado y `kickoff_verified=false`. |
| `FOOTBALL_KICKOFF_TIMEOUT_SECONDS` | Tiempo máximo de la consulta de inicio. Un fallo no bloquea el registro: se marca `unverified` o se usa el `kickoff` declarado. |
| `PUBLIC_BASE_URL` | URL pública HTTPS que se añade a los `servers` de los contratos OpenAPI. Déjala vacía en local. |

Aunque la verificación esté activa, un registro tardío se acepta con
`timing.status=late`. La verificación solo decide si se puede afirmar que llegó
antes del inicio.

## CORS

Desarrollo:

```dotenv
CORS_ORIGINS=http://localhost:4200,http://127.0.0.1:4200
CORS_ORIGIN_REGEX=^http://(localhost|127\.0\.0\.1):\d+$
```

Producción con Netlify:

```dotenv
CORS_ORIGINS=https://bet-app-web.netlify.app
CORS_ORIGIN_REGEX=
```

`CORS_ORIGINS` es una lista separada por comas. `CORS_ORIGIN_REGEX` permite
cualquier puerto local; déjalo vacío en producción.

## Tiempos de espera y caché

```dotenv
REQUEST_TIMEOUT_SECONDS=20
CACHE_TTL_SECONDS=900
```

## Enriquecimiento de béisbol

```dotenv
WEB_ENRICHMENT_ENABLED=true
WEB_ENRICHMENT_TIMEOUT_SECONDS=25
BASEBALL_SETTLEMENT_ENABLED=true
BASEBALL_SETTLEMENT_INTERVAL_SECONDS=600
```

El enriquecimiento y el calendario de béisbol se obtienen con parsers
deterministas sobre páginas públicas de MLB. No se requieren servicios externos
de inferencia.

La liquidación automática se ejecuta cada `BASEBALL_SETTLEMENT_INTERVAL_SECONDS`
segundos y solo liquida juegos con resultado final disponible.

## Registro

```dotenv
LOG_LEVEL=INFO
LOG_API_RESPONSES=true
API_LOG_PREVIEW_CHARS=2000
```

`LOG_API_RESPONSES` controla si se registran las respuestas de proveedores
externos; `API_LOG_PREVIEW_CHARS` limita cuántos caracteres se imprimen.

## Siguiente paso

- [Iniciar la API](EJECUCION.md)
- [Endpoints](ENDPOINTS.md)
