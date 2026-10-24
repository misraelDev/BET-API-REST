# BET Analytics API

API REST construida con FastAPI para registrar, almacenar, consultar y liquidar
apuestas deportivas. El backend alimenta el frontend Angular de BET Analytics
y persiste los registros en MongoDB.

El registro es **manual**: la API ya no calcula probabilidades ni genera picks.
El analista registra el partido, su selección y, si quiere, sus mercados.

La documentación está dividida por tema en [`docs/`](docs/).

## Deportes disponibles

| Deporte | Fuente para liquidar | Registro |
| --- | --- | --- |
| Fútbol | TheSportsDB (Liga MX, Brasileirão) y ESPN (Leagues Cup) | `manual-v1` |
| Básquetbol | ESPN public web (NBA, WNBA, Summer League) | `manual-v1` |
| Béisbol | MLB public web y resultados oficiales de KBO | `manual-v1` |
| Tenis | Scoreboard público de ESPN (ATP/WTA) | `manual-v1` |

Todas las rutas de registro, consulta y liquidación están en
[`docs/ENDPOINTS.md`](docs/ENDPOINTS.md). Para preparar los partidos y sus
identificadores, usa la [guía del analista](docs/ANALISTA.md).

En fútbol, además del registro simple, existe un contrato versionado por
selección: `POST /api/v1/football/predictions` acepta lotes de hasta 100
selecciones, conserva todas las versiones, registra `received_at` del servidor,
compara contra el inicio verificado y liquida 22 mercados por periodo. El
catálogo y las reglas están en
`GET /api/v1/football/predictions/markets`.

## Inicio rápido

```powershell
cd C:\Users\Misrael\Documents\WEBS\BET\BET-API-REST

# 1. Entorno virtual del proyecto (siempre en .venv)
python -m venv .venv

# 2. Dependencias
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Configuración
Copy-Item .env.example .env

# 4. Arrancar la API
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Comprobar:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
# {"status":"ok","database":"connected"}
```

| Recurso | URL |
| --- | --- |
| Swagger UI | <http://127.0.0.1:8000/docs> |
| ReDoc | <http://127.0.0.1:8000/redoc> |
| Catálogo de deportes | <http://127.0.0.1:8000/api/v1/sports> |

> Todos los comandos usan el `.venv` del proyecto. No hay entornos alternativos.

## Documentación

| Documento | Contenido |
| --- | --- |
| [Guía del analista](docs/ANALISTA.md) | Fuentes por deporte, `event_id`, contrato de registro, pronósticos versionados y mercados. |
| [Arquitectura](docs/ARQUITECTURA.md) | Stack, estructura de carpetas y flujo de una petición. |
| [Instalación](docs/INSTALACION.md) | Requisitos, creación del `.venv` y verificación. |
| [Configuración](docs/CONFIGURACION.md) | Variables de `.env`: proveedores, MongoDB, CORS, caché y registro. |
| [Ejecución](docs/EJECUCION.md) | Arranque con Uvicorn, URLs y valores de `/health`. |
| [Endpoints](docs/ENDPOINTS.md) | Rutas por deporte, parámetros, paginación y errores. |
| [Ejemplos](docs/EJEMPLOS.md) | Peticiones listas para PowerShell y curl. |
| [Persistencia](docs/PERSISTENCIA.md) | `upsert` en MongoDB, consultas, mercados y liquidación. |
| [Pruebas](docs/PRUEBAS.md) | Ejecutar Pytest y cobertura por archivo. |
| [Docker](docs/DOCKER.md) | Construir la imagen, puerto, healthcheck y redes. |
| [Despliegue](docs/DESPLIEGUE.md) | Variables sensibles, CORS de producción y verificación. |
| [Seguridad](docs/SEGURIDAD.md) | Credenciales, CORS, TLS y ausencia de autenticación. |
| [Limitaciones](docs/LIMITACIONES.md) | Alcance de las fuentes públicas y del registro manual. |
| [OpenAPI](docs/OPENAPI.md) | Contratos por deporte en `openapi/`, visores y regeneración. |
