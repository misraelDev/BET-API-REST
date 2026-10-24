# Contratos OpenAPI

Cada archivo contiene **solo** las rutas de un deporte (más el registro de
prompts) y los esquemas que esas rutas referencian. No hay un `openapi.yaml` con
todo mezclado.

| Archivo | Contenido | Rutas | Operaciones | Esquemas |
| --- | --- | --- | --- | --- |
| [`system.yaml`](system.yaml) | `/health`, `/api/v1/sports`, `/api/v1/records` | 3 | 3 | 6 |
| [`football.yaml`](football.yaml) | `/api/v1/football/*` | 6 | 8 | 31 |
| [`nba.yaml`](nba.yaml) | `/api/v1/nba/*` | 2 | 2 | 6 |
| [`baseball.yaml`](baseball.yaml) | `/api/v1/baseball/*` | 5 | 5 | 7 |
| [`tennis.yaml`](tennis.yaml) | `/api/v1/tennis/*` | 3 | 3 | 7 |
| [`prompts.yaml`](prompts.yaml) | `/api/v1/prompts/*` | 2 | 3 | 7 |

Cada archivo es autocontenido: sus `$ref` apuntan a su propio bloque
`components`, sin esquemas huérfanos ni referencias externas.

El registro manual (`POST /api/v1/records`) vive en `system.yaml` porque es
transversal a los cuatro deportes.

## Versión

Los seis archivos comparten la versión OpenAPI `3.1.0` y la versión de la API
`1.5.0`.

## Regenerar

```powershell
cd C:\Users\Misrael\Documents\WEBS\BET\BET-API-REST
.\.venv\Scripts\python.exe scripts\generate_openapi.py
```

El comando lee `app.main:app`, separa las rutas y reescribe los seis archivos.
Si `PUBLIC_BASE_URL` está definida, se añade como servidor adicional en los
contratos.

Verificar que están al día sin escribir nada:

```powershell
.\.venv\Scripts\python.exe scripts\generate_openapi.py --check
```

## Abrirlos

1. Entra en <https://editor.swagger.io/>.
2. **File → Import file** y selecciona el archivo del deporte.
3. Para la instancia desplegada abre
   <https://start-bet-api-rest.xzpbpr.easypanel.host/openapi.json> o apunta un
   Swagger UI a ese recurso. En local, usa `http://127.0.0.1:8000/openapi.json`.

## Documentos relacionados

- [Endpoints](../docs/ENDPOINTS.md)
- [Guía del analista](../docs/ANALISTA.md)
- [Documentación general de OpenAPI](../docs/OPENAPI.md)
