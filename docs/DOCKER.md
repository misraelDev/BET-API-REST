# Docker

## Construir la imagen

```powershell
cd C:\Users\Misrael\Documents\WEBS\BET\BET-API-REST
docker build -t bet-api-rest .
```

La imagen parte de `python:3.13-slim`, instala `requirements.txt` y ejecuta la
aplicación con un usuario sin privilegios.

## Ejecutar con las variables del archivo `.env`

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

## Puerto

La imagen respeta la variable `PORT` (valor por defecto `8000`):

```powershell
docker run --rm --env-file .env -e PORT=8010 -p 8010:8010 bet-api-rest
```

## Healthcheck

El `Dockerfile` define un healthcheck que consulta `/health` cada 30 segundos:

```text
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3
```

## Conexiones desde el contenedor

Dentro de Docker, `127.0.0.1` apunta al propio contenedor.

Si MongoDB se ejecuta en Windows, utiliza:

```dotenv
MONGODB_URI=mongodb://usuario:password@host.docker.internal:27017/?tls=false
```

Si MongoDB está en otro contenedor, colócalos en la misma red Docker y usa el
nombre del servicio como host:

```powershell
docker network create bet-net
docker run --rm --network bet-net --env-file .env -p 8000:8000 bet-api-rest
```

## Archivos excluidos

`.dockerignore` deja fuera `.env`, `.venv`, `tests` y cachés, de modo que las
credenciales no viajan dentro de la imagen.

## Documentos relacionados

- [Despliegue](DESPLIEGUE.md)
- [Seguridad](SEGURIDAD.md)
