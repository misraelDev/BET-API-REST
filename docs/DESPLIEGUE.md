# Despliegue

## Puerto

La imagen acepta la variable `PORT`, utilizada por plataformas como Render,
Railway o Fly.io:

```text
PORT=8000
```

El comando del contenedor es:

```text
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Variables sensibles

Configura las credenciales desde el panel de la plataforma, no mediante archivos
incluidos en Git:

- `MONGODB_URI`
- `API_FOOTBALL_KEY`
- `FOOTBALL_DATA_API_KEY`

El resto de variables puede tomar sus valores por defecto.

## CORS en producción

Restringe los orígenes al dominio real del frontend:

```dotenv
CORS_ORIGINS=https://bet-app-web.netlify.app
CORS_ORIGIN_REGEX=
```

## Verificación posterior

1. Comprueba `GET /health`: debe responder `{"status":"ok","database":"connected"}`.
2. Comprueba `GET /api/v1/sports`: debe listar los cuatro deportes.
3. Actualiza `apiUrl` en el environment de producción del frontend Angular.

## Documentos relacionados

- [Docker](DOCKER.md)
- [Configuración](CONFIGURACION.md)
- [Seguridad](SEGURIDAD.md)
