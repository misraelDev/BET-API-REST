# Ejecución

## Iniciar la API

1. Abre una terminal en la carpeta del proyecto:

```powershell
cd C:\Users\Misrael\Documents\WEBS\BET\BET-API-REST
```

2. Asegúrate de tener el archivo `.env` (si no existe, créalo desde el ejemplo):

```powershell
Copy-Item .env.example .env
```

3. Inicia el servidor con Uvicorn:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

4. Verifica que responde:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
# {"status":"ok","database":"connected"}
```

5. Detén el servidor con `Ctrl+C`.

> `--reload` reinicia el servidor al guardar cambios; úsalo solo en desarrollo.
> Si el puerto 8000 está ocupado, cambia `--port 8000` por otro, por ejemplo `8010`.

## URLs

| Recurso | URL |
| --- | --- |
| API | `http://127.0.0.1:8000` |
| Swagger UI | `http://127.0.0.1:8000/docs` |
| ReDoc | `http://127.0.0.1:8000/redoc` |
| Contrato OpenAPI (JSON) | `http://127.0.0.1:8000/openapi.json` |
| Contrato OpenAPI (YAML) | [`openapi/`](../openapi/README.md) |
| Salud | `http://127.0.0.1:8000/health` |
| Catálogo de deportes | `http://127.0.0.1:8000/api/v1/sports` |

## Valores de `/health`

| Valor de `database` | Significado |
| --- | --- |
| `connected` | MongoDB conectado y persistencia activa. |
| `disabled` | No hay `MONGODB_URI` configurada. |

## Sondeos externos en el log

Si ves una línea como:

```text
INFO: 127.0.0.1:53283 - "GET /v1/models HTTP/1.1" 404 Not Found
```

no proviene de esta API: `/v1/models` no existe en el proyecto. Es el sondeo de
descubrimiento de un cliente local compatible con OpenAI/vLLM (por ejemplo,
OpenCode, que prueba `http://127.0.0.1:8000/v1`) contra el puerto donde escucha
la API. Es inofensivo; desaparece si la API se mueve a otro puerto.

## Siguiente paso

- [Endpoints](ENDPOINTS.md)
- [Ejemplos de petición](EJEMPLOS.md)
