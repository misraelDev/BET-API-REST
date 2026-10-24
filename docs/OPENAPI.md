# Contrato OpenAPI

La especificación se publica **separada por deporte** en [`openapi/`](../openapi/).
No existe un archivo único con todas las rutas.

| Archivo | Contenido | Rutas | Operaciones |
| --- | --- | --- | --- |
| [`system.yaml`](../openapi/system.yaml) | `/health`, `/api/v1/sports`, `/api/v1/records` | 3 | 3 |
| [`football.yaml`](../openapi/football.yaml) | `/api/v1/football/*` | 6 | 8 |
| [`nba.yaml`](../openapi/nba.yaml) | `/api/v1/nba/*` | 2 | 2 |
| [`baseball.yaml`](../openapi/baseball.yaml) | `/api/v1/baseball/*` | 5 | 5 |
| [`tennis.yaml`](../openapi/tennis.yaml) | `/api/v1/tennis/*` | 3 | 3 |

Total: 19 rutas y 21 operaciones, repartidas entre los cinco contratos.

El registro manual (`POST /api/v1/records`) se documenta en `system.yaml` porque
es transversal a los cuatro deportes. Las seis rutas de pronósticos de fútbol
(8 operaciones) incluyen petición, respuesta y errores con ejemplos: catálogo,
lote, listado, detalle y evaluaciones posteriores.

## Contenido de cada archivo

- Versión OpenAPI 3.1.0 y versión de API 1.3.0.
- Servidores `http://127.0.0.1:8000` y `http://localhost:8000`; si defines
  `PUBLIC_BASE_URL`, se añade como servidor adicional.
- Solo los `tags` del deporte correspondiente.
- Bloque `components` recortado: únicamente los esquemas que esas rutas
  referencian, sin dependencias externas ni esquemas huérfanos.
- Parámetros de query, cuerpos de petición, respuestas, ejemplos y headers de
  paginación de los endpoints `/results` y `/predictions`.

## Consultarlo en ejecución

| Recurso | URL |
| --- | --- |
| Swagger UI | `http://127.0.0.1:8000/docs` |
| ReDoc | `http://127.0.0.1:8000/redoc` |
| JSON completo en vivo | `http://127.0.0.1:8000/openapi.json` |

`/openapi.json` sigue devolviendo el contrato completo de la aplicación; los
archivos de `openapi/` son la versión dividida para revisión y edición.

## Cargarlo en un editor

1. Abre <https://editor.swagger.io/>.
2. Menú **File → Import file**.
3. Selecciona el archivo del deporte, por ejemplo `openapi/football.yaml`.

## Regenerar los archivos

Los contratos se derivan de la app; después de añadir o cambiar rutas hay que
regenerarlos:

```powershell
cd C:\Users\Misrael\Documents\WEBS\BET\BET-API-REST
.\.venv\Scripts\python.exe scripts\generate_openapi.py
```

Para verificar en CI que están al día, sin escribir:

```powershell
.\.venv\Scripts\python.exe scripts\generate_openapi.py --check
```

## Documentos relacionados

- [Índice de contratos](../openapi/README.md)
- [Endpoints](ENDPOINTS.md)
- [Ejecución](EJECUCION.md)
