# Seguridad

- `.env` está excluido de la imagen Docker y de Git.
- La aplicación se ejecuta con un usuario sin privilegios dentro del contenedor.
- No incluyas credenciales en el repositorio.
- Restringe `CORS_ORIGINS` a los dominios reales de producción y deja
  `CORS_ORIGIN_REGEX` vacío fuera de desarrollo.
- No expongas MongoDB directamente a Internet sin autenticación y controles de
  red.
- Usa TLS en la cadena de conexión de MongoDB cuando el tráfico salga de la red
  local.
- Rota las claves de `API_FOOTBALL_KEY` y `FOOTBALL_DATA_API_KEY` si se filtran.
- La API no implementa autenticación: protégela con un proxy, una red privada o
  reglas de firewall si se publica fuera de localhost.
- Los endpoints de pronósticos de fútbol (`/api/v1/football/predictions`)
  tampoco piden credenciales. Cualquiera con acceso a la API puede registrar,
  versionar o evaluar selecciones.
- El `POST /api/v1/prompts/{sport}/{prompt_type}` tampoco tiene autenticación:
  cualquier cliente que alcance la API puede publicar una nueva versión
  vigente. El compare-and-set evita pisar revisiones concurrentes, pero no
  reemplaza autorización; limita el acceso desde el proxy o la red.

## Publicación con HTTPS

Antes de exponer la API fuera de localhost:

1. Termina TLS en un reverse proxy (Nginx, Caddy, Traefik o el balanceador del
   proveedor) y deja Uvicorn escuchando solo en la red interna.
2. Redirige todo el tráfico HTTP a HTTPS.
3. Publica `PUBLIC_BASE_URL=https://api.tudominio.com` para que los contratos
   OpenAPI anuncien el servidor correcto.
4. Restringe `CORS_ORIGINS` al dominio real del frontend.
5. Mantén `MONGODB_URI`, `API_FOOTBALL_KEY` y `FOOTBALL_DATA_API_KEY` solo en el
   backend (variables de entorno o gestor de secretos). Nunca en el frontend,
   en el repositorio ni en la documentación publicada.
6. Si el acceso debe ser privado, añade autenticación en el proxy o en una
   capa intermedia: la aplicación no la implementa.

Ejemplo mínimo de Nginx:

```nginx
server {
    listen 443 ssl;
    server_name api.tudominio.com;

    ssl_certificate     /etc/letsencrypt/live/api.tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.tudominio.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name api.tudominio.com;
    return 301 https://$host$request_uri;
}
```

La aplicación confía en el proxy para el esquema y la IP de origen; no acepta
TLS directo. Documenta el certificado y su renovación en el despliegue.

## CORS

Los orígenes permitidos se definen con `CORS_ORIGINS` (lista separada por comas)
y, opcionalmente, con `CORS_ORIGIN_REGEX` para patrones.

Los headers de paginación expuestos al navegador son:

```text
X-Total-Count
X-Page
X-Page-Size
X-Total-Pages
```

## Documentos relacionados

- [Configuración](CONFIGURACION.md)
- [Despliegue](DESPLIEGUE.md)
