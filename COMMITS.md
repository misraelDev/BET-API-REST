# Convención de commits de BET Analytics API

Esta guía define cómo registrar cambios en el backend FastAPI de BET Analytics. Cada commit debe ser pequeño, revisable y explicar claramente el motivo y el beneficio del cambio.

## Regla principal

Cada commit debe:

- Representar un solo cambio lógico.
- Llevar un número consecutivo único al inicio del título.
- Estar escrito en español.
- Seguir Conventional Commits.
- Explicar `por qué` y `para qué`.
- Evitar credenciales, archivos generados y trailers automáticos.

Los comandos Git no deben ejecutarse automáticamente. El desarrollador debe revisarlos y ejecutarlos manualmente.

## Formato obligatorio

```text
<número> - <tipo>(<ámbito>): <título breve>

por qué: <problema, necesidad o contexto>
para qué: <resultado o beneficio esperado>
```

Ejemplo:

```powershell
git commit -m "1 - feat(tenis): agregar liquidación de mercados" `
  -m "por qué: las predicciones permanecían pendientes después del partido" `
  -m "para qué: registrar mercados ganados, perdidos y unidades netas"
```

### Numeración consecutiva

El número se incrementa por cada commit. Consulta el último número usado en
`git log` y utiliza el siguiente entero (`último + 1`). Si todavía no hay
commits numerados, comienza en `1`. No reutilices números ni reinicies la
secuencia al cambiar de rama. Git no asigna este número automáticamente: quien
crea el commit debe comprobar el historial y escribirlo en el mensaje.

## Tipos permitidos

| Tipo | Uso |
| --- | --- |
| `feat` | Nueva capacidad, endpoint o modelo |
| `fix` | Corrección de un error |
| `docs` | Documentación |
| `style` | Formato sin cambio de comportamiento |
| `refactor` | Reorganización sin cambiar contratos |
| `perf` | Rendimiento, caché o reducción de consultas |
| `test` | Pruebas nuevas o corregidas |
| `chore` | Mantenimiento interno |
| `ci` | Integración o despliegue continuo |
| `build` | Docker, dependencias o empaquetado |

## Ámbitos del backend

| Ámbito | Contenido |
| --- | --- |
| `futbol` | Fuentes, modelo y endpoints de fútbol |
| `beisbol` | MLB, KBO, mercados y liquidación |
| `tenis` | ATP, WTA, ELO, mercados y resultados |
| `basquetbol` | NBA, WNBA y Summer League |
| `api` | Contratos y comportamiento HTTP compartido |
| `db` | MongoDB, índices, consultas y migraciones |
| `modelos` | Modelos Pydantic y contratos |
| `fuentes` | Clientes HTTP y normalización de datos públicos |
| `prediccion` | Algoritmos, pesos y probabilidades |
| `liquidacion` | Validación de mercados y unidades |
| `config` | Variables de entorno, CORS y settings |
| `docker` | Imagen, healthcheck y despliegue |
| `deps` | Dependencias Python |
| `docs` | README y documentación técnica |

## Reglas de redacción

1. Usar imperativo: `agregar`, `corregir`, `actualizar`, `eliminar`.
2. Mantener el título en 72 caracteres o menos.
3. No terminar el título con punto.
4. Usar tipo y ámbito en minúsculas.
5. Incluir siempre `por qué` y `para qué`.
6. No mezclar cambios de deportes distintos en un mismo commit.
7. Separar cambios de infraestructura de cambios predictivos.
8. Declarar cambios incompatibles en contratos HTTP.
9. No usar mensajes genéricos como `cambios`, `fix`, `update` o `WIP`.

## Ejemplos

### Nueva fuente pública

```powershell
git add app/sports/nba/public_client.py
git commit -m "<número> - feat(basquetbol): consultar cartelera pública de ESPN" `
  -m "por qué: el proveedor anterior requería una cuenta suspendida" `
  -m "para qué: obtener NBA y WNBA sin depender de una API key"
```

### Corrección de duplicados

```powershell
git add app/database/repository.py tests/test_repository.py
git commit -m "<número> - fix(db): evitar predicciones duplicadas de tenis" `
  -m "por qué: la versión del modelo formaba parte de la identidad" `
  -m "para qué: actualizar el partido existente mediante upsert"
```

### Cambio de algoritmo

```powershell
git add app/sports/tennis/service.py tests/test_tennis_service.py
git commit -m "<número> - feat(prediccion): ponderar forma reciente de cada tenista" `
  -m "por qué: el modelo dependía demasiado del historial directo" `
  -m "para qué: producir señales cuando los jugadores no tienen H2H"
```

### Docker

```powershell
git add Dockerfile .dockerignore README.md
git commit -m "<número> - build(docker): contenerizar API de predicciones" `
  -m "por qué: el backend necesitaba un entorno reproducible" `
  -m "para qué: desplegar FastAPI con dependencias y healthcheck"
```

### Documentación

```powershell
git add README.md COMMITS.md
git commit -m "<número> - docs(proyecto): documentar backend y contribución" `
  -m "por qué: la documentación anterior no reflejaba la arquitectura actual" `
  -m "para qué: facilitar instalación, despliegue y mantenimiento"
```

## Commits atómicos

Ejemplo de separación correcta para una nueva liga:

1. Cliente y normalización de la fuente.
2. Ajuste del modelo predictivo.
3. Router y contratos Pydantic.
4. Persistencia y liquidación.
5. Pruebas.
6. Documentación.

No mezcles en un solo commit:

- Cambios de fútbol y tenis.
- Una migración de MongoDB y un rediseño de modelos no relacionado.
- Docker y una modificación del algoritmo.
- Correcciones funcionales con formateo masivo.

## Flujo recomendado

### 1. Revisar cambios

```powershell
git status
git diff
```

### 2. Ejecutar pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### 3. Verificar importación de FastAPI

```powershell
.\.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"
```

### 4. Verificar Docker cuando corresponda

```powershell
docker build -t bet-api-rest .
```

### 5. Agregar archivos relacionados

```powershell
git add <archivos-relacionados>
```

Evita `git add .` cuando existan cambios independientes.

### 6. Crear el commit

```powershell
git commit -m "<número> - tipo(ámbito): título" `
  -m "por qué: motivo" `
  -m "para qué: objetivo"
```

### 7. Revisar el commit

```powershell
git show --stat
git log -1 --format=full
```

### 8. Subir la rama

```powershell
git push origin <nombre-rama>
```

Respeta las reglas de protección del repositorio y utiliza Pull Requests cuando la rama de destino esté protegida.

## Cambios incompatibles

Cuando se modifique una ruta, un payload o una respuesta consumida por Angular:

```powershell
git commit -m "<número> - feat(api): unificar respuesta paginada" `
  -m "por qué: los deportes devolvían contratos diferentes" `
  -m "para qué: simplificar el consumo desde el frontend" `
  -m "BREAKING CHANGE: cambia la estructura de los endpoints results"
```

## Seguridad

Nunca incluir en commits:

- `.env`
- Credenciales de MongoDB
- API keys o tokens
- URLs internas con contraseñas
- Dumps de base de datos
- Logs con payloads sensibles
- Certificados o claves privadas

Antes de agregar cambios de configuración:

```powershell
git diff -- .env.example app/core/config.py
```

`.env.example` debe contener únicamente valores ficticios.

## Archivos generados

No incluir:

```text
.venv/
__pycache__/
.pytest_cache/
*.pyc
*.log
.env
```

## Codificación UTF-8 en Windows

```powershell
git config --global core.quotepath false
git config --global i18n.commitencoding utf-8
git config --global i18n.logoutputencoding utf-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:LANG = "es_ES.UTF-8"
```

## Lista de comprobación

- [ ] El commit contiene un único cambio lógico.
- [ ] El título está en español y en imperativo.
- [ ] Se incluyeron `por qué` y `para qué`.
- [ ] No se incluyeron secretos ni `.env`.
- [ ] Los contratos Pydantic son compatibles o declaran el cambio rompedor.
- [ ] Las fuentes externas tienen manejo de errores y timeout.
- [ ] La persistencia evita duplicados.
- [ ] Las pruebas pasan.
- [ ] La documentación fue actualizada cuando corresponde.
- [ ] La rama de destino es correcta.

Un buen commit debe explicar qué cambió, por qué fue necesario y para qué mejora BET Analytics API.
