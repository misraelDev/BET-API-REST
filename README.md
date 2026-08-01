# BET Analytics API

API REST construida con FastAPI para generar, almacenar, consultar y liquidar predicciones deportivas. El backend alimenta el frontend Angular de BET Analytics y persiste resultados en MongoDB.

## Deportes disponibles

| Deporte | Fuente principal | Modelo |
| --- | --- | --- |
| Fútbol | Fuentes públicas, football-data.org y fallback configurado | Fusión ponderada |
| Béisbol | Sitios públicos MLB/KBO y enriquecimiento opcional con OmniRoute | Récord y diferencial de carreras |
| Tenis | Scoreboard público de ESPN para ATP/WTA | ELO, forma, sets, juegos y H2H |
| Básquetbol | Scoreboard y standings públicos de ESPN | Récord, margen, local/visitante y forma |

Las probabilidades son estimaciones estadísticas, no garantías de resultados.

## Tecnologías

- Python 3.13
- FastAPI
- Uvicorn
- Pydantic
- HTTPX
- MongoDB con PyMongo asíncrono
- Pytest

## Estructura

```text
app/
├── core/             # Configuración
├── database/         # Persistencia y liquidación
├── integrations/     # OmniRoute
├── shared/           # Modelos y utilidades comunes
├── sports/
│   ├── baseball/
│   ├── football/
│   ├── nba/
│   └── tennis/
└── main.py           # Aplicación, lifespan y routers
```

Cada deporte mantiene separados sus modelos, router, cliente de datos y servicio predictivo.

## Requisitos locales

- Python 3.13 recomendado
- MongoDB accesible desde el backend
- OmniRoute opcional para enriquecimiento de béisbol

## Instalación local

```powershell
cd C:\Users\misra\Documents\BET\BET-API-REST
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` con los valores de tu entorno. Nunca publiques ese archivo.

## Variables de entorno

### MongoDB

```dotenv
MONGODB_URI=mongodb://usuario:password@host:27017/?tls=false
MONGODB_DATABASE=sports_db
MONGODB_COLLECTION=predictions
MONGODB_REQUIRED=false
```

Si `MONGODB_REQUIRED=true`, la aplicación no inicia cuando MongoDB no está disponible.

### CORS

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

### Fuentes y tiempos de espera

```dotenv
REQUEST_TIMEOUT_SECONDS=20
CACHE_TTL_SECONDS=900
WEB_ENRICHMENT_ENABLED=true
WEB_ENRICHMENT_TIMEOUT_SECONDS=25
```

### OmniRoute opcional

```dotenv
OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1
OMNIROUTE_API_KEY=
OMNIROUTE_MODEL=oc/deepseek-v4-flash-free
```

### Liquidación automática de béisbol

```dotenv
BASEBALL_SETTLEMENT_ENABLED=true
BASEBALL_SETTLEMENT_INTERVAL_SECONDS=600
```

## Ejecutar localmente

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

URLs:

- API: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Salud: `http://127.0.0.1:8000/health`
- Catálogo: `http://127.0.0.1:8000/api/v1/sports`

## Endpoints

### Fútbol

```text
GET  /api/v1/football/predictions
GET  /api/v1/football/results
POST /api/v1/football/results/update
```

### Béisbol

```text
GET  /api/v1/baseball/predictions
POST /api/v1/baseball/predictions
GET  /api/v1/baseball/results
POST /api/v1/baseball/results/update
POST /api/v1/baseball/results/settle
GET  /api/v1/baseball/official-results
GET  /api/v1/baseball/stats
```

Ligas: `mlb`, `kbo`, `all`.

### Tenis

```text
GET  /api/v1/tennis/matches/count
GET  /api/v1/tennis/predictions
POST /api/v1/tennis/predictions
GET  /api/v1/tennis/results
POST /api/v1/tennis/results/update
```

Circuitos: `atp`, `wta`, `all`.

### Básquetbol

```text
GET  /api/v1/nba/predictions
POST /api/v1/nba/predictions
GET  /api/v1/nba/results
POST /api/v1/nba/results/update
```

Ligas: `nba`, `wnba`, `summer_league`, `all`.

## Ejemplo de petición

```powershell
$body = @{
  date = "2026-08-01"
  timezone = "America/Mexico_City"
  league = "wnba"
  limit = 20
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/nba/predictions `
  -ContentType application/json `
  -Body $body
```

## Persistencia

La generación ejecuta un `upsert` en MongoDB. Si el partido ya existe para la misma identidad, se actualiza en lugar de crear un duplicado.

Los endpoints `/results` consultan MongoDB y exponen paginación mediante headers:

```text
X-Total-Count
X-Page
X-Page-Size
X-Total-Pages
```

La liquidación guarda el resultado de cada mercado y sus unidades:

- `won`: `+100`
- `lost`: `-100`
- `push`: `0`
- Sin finalizar: pendiente

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Docker

### Construir la imagen

```powershell
docker build -t bet-api-rest .
```

### Ejecutar con variables del archivo `.env`

```powershell
docker run --rm `
  --name bet-api-rest `
  --env-file .env `
  -p 8000:8000 `
  bet-api-rest
```

Comprueba:

```text
http://127.0.0.1:8000/health
```

### Conexiones desde el contenedor

Dentro de Docker, `127.0.0.1` apunta al propio contenedor.

Si MongoDB u OmniRoute se ejecutan en Windows, utiliza:

```dotenv
MONGODB_URI=mongodb://usuario:password@host.docker.internal:27017/?tls=false
OMNIROUTE_BASE_URL=http://host.docker.internal:20128/v1
```

Si los servicios están en otros contenedores, colócalos en la misma red Docker y utiliza sus nombres de servicio como host.

## Despliegue

La imagen acepta la variable `PORT`, utilizada por plataformas como Render, Railway o Fly.io:

```text
PORT=8000
```

Configura las variables sensibles desde el panel de la plataforma, no mediante archivos incluidos en Git.

Después de desplegar el backend, actualiza `apiUrl` en el environment de producción del frontend Angular.

## Seguridad

- `.env` está excluido de la imagen Docker.
- La aplicación se ejecuta con un usuario sin privilegios.
- No incluyas credenciales en el repositorio.
- Restringe `CORS_ORIGINS` a los dominios reales de producción.
- No expongas MongoDB directamente a Internet sin autenticación y controles de red.

## Limitaciones

- Las fuentes públicas pueden cambiar su HTML o formato sin previo aviso.
- Los modelos reducen la señal cuando faltan datos.
- Las probabilidades no representan certeza.
- Lesiones, alineaciones y cambios de última hora no siempre están disponibles.
