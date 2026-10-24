# Arquitectura

## Stack

| Componente | Tecnología |
| --- | --- |
| Lenguaje | Python 3.12+ (la imagen Docker usa 3.13) |
| Framework | FastAPI 0.116 |
| Servidor | Uvicorn 0.35 |
| Validación | Pydantic 2 |
| Cliente HTTP | HTTPX |
| Base de datos | MongoDB con PyMongo asíncrono |
| Pruebas | Pytest |

## Estructura

```text
app/
├── core/             # Configuración (settings y .env)
├── database/         # Persistencia, consultas y liquidación heredada
├── records/          # Registro manual: modelos, servicio y router
├── shared/           # Modelos, paginación y utilidades comunes
├── sports/
│   ├── baseball/     # Modelos, router, cliente, enriquecimiento y liquidación
│   ├── football/
│   │   ├── predictions/  # Catálogo, modelos, observación, liquidación,
│   │   │                 # repositorio, servicio y router versionado
│   │   ├── espn_results_client.py
│   │   └── ...
│   ├── nba/
│   └── tennis/
└── main.py           # Aplicación, lifespan y routers
```

Cada deporte mantiene separados sus modelos, router, cliente de datos y
servicio. El router valida la petición, el servicio arma el documento y el
repositorio lo persiste. El registro es transversal y vive en `app/records/`.

## Flujo de una petición

### Registro

```text
router (/api/v1/records)  ->  ManualRecordService  ->  repository (MongoDB)
```

- `router`: valida el cuerpo con Pydantic y traduce errores a HTTP.
- `service`: normaliza la liga, resuelve `event_id` y `kickoff`, y construye el
  documento con el subdocumento `prediction`.
- `repository`: hace `upsert` por identidad y devuelve el documento guardado.

### Consulta y liquidación

```text
router  ->  repository (MongoDB)
router  ->  cliente de resultados oficiales  ->  repository
```

- Los `GET /results` leen de MongoDB y aplican filtros y paginación.
- Los `POST /results/update` piden el resultado oficial a la fuente, comparan
  con el registro y escriben `settlement`.
- El bucle de liquidación de béisbol se ejecuta en el `lifespan` si
  `BASEBALL_SETTLEMENT_ENABLED` está activo.

### Pronósticos de fútbol versionados

```text
router (/api/v1/football/predictions)
  -> FootballPredictionService
       -> EspnKickoffResolver (verifica el inicio)
       -> FootballPredictionRepository (football_predictions)
  -> POST /results/update
       -> FootballPredictionService.settle_date
            -> ESPN summary -> FootballObservation
            -> settle_prediction (motor puro)
            -> FootballPredictionRepository.update_settlement
```

- `catalog.py` concentra ligas, mercados, periodos y reglas; es la fuente de
  verdad de la validación.
- `observation.py` traduce el resumen de ESPN a una `FootballObservation`
  (marcadores por tiempo, goles, tarjetas, córners, remates y plantillas).
- `settlement.py` es puro: recibe selección y observación y devuelve estado,
  evidencia y regla aplicada.
- `repository.py` versiona con `insert` y mantiene los índices únicos de
  idempotencia y versión.
- `service.py` orquesta lote, versiones, filtros, evaluaciones y liquidación.
- Las evaluaciones posteriores viven en otra colección y nunca reescriben el
  pronóstico.

## Deportes y fuentes

| Deporte | Fuente para liquidar | Versión del registro |
| --- | --- | --- |
| Fútbol | TheSportsDB (Liga MX, Brasileirão), ESPN (Leagues Cup) y resumen público de ESPN para los pronósticos versionados | `manual-v1` / `football-settlement-v2` |
| Básquetbol | ESPN public web (NBA, WNBA, Summer League) | `manual-v1` |
| Béisbol | MLB public web y resultados oficiales de KBO | `manual-v1` |
| Tenis | Scoreboard público de ESPN (ATP/WTA) | `manual-v1` |

La API ya no calcula probabilidades: solo guarda, consulta y liquida lo que
registra el analista. En fútbol, cada selección versionada se liquida con la
regla `football-settlement-v2` y guarda la evidencia observada.

## Documentos relacionados

- [Guía del analista](ANALISTA.md)
- [Instalación](INSTALACION.md)
- [Configuración](CONFIGURACION.md)
- [Endpoints](ENDPOINTS.md)
- [Persistencia](PERSISTENCIA.md)
