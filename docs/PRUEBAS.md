# Pruebas

## Ejecutar la suite

```powershell
cd C:\Users\Misrael\Documents\WEBS\BET\BET-API-REST
.\.venv\Scripts\python.exe -m pytest -q
```

La suite actual tiene **199 pruebas**.

## Ejecutar un archivo concreto

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_records.py -q
```

## Ejecutar una prueba concreta

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_records.py -q -k baseball
```

## Cobertura por archivo

| Archivo | Área |
| --- | --- |
| `test_football_data_client.py` | Cliente de football-data.org. |
| `test_football_fusion.py` | Fusión ponderada de fútbol. |
| `test_football_market_stats.py` | Estadísticas de mercado de fútbol. |
| `test_football_observations.py` | Resumen de ESPN → `FootballObservation` (participantes, segunda amarilla, plantillas, tiempos extra). |
| `test_football_predictions_models.py` | Esquema del lote, validación mercado × periodo y líneas. |
| `test_football_predictions_router.py` | Contrato HTTP: 201/200/409/422/503, listado, detalle y evaluaciones. |
| `test_football_predictions_service.py` | Versionado, idempotencia, filtros, evaluaciones y liquidación por fecha. |
| `test_football_predictions_repository.py` | Índices únicos, compare-and-set de versiones y recuperación ante colisiones. |
| `test_prompts.py` | Publicación de versiones, consulta exacta/vigente, conflicto de base y rutas HTTP. |
| `test_prompts_repository.py` | Índices y compare-and-set para historial de prompts. |
| `test_records.py` | Persistencia y validación de referencias de prompt en picks manuales. |
| `test_football_settlement.py` | Motor de liquidación por mercado y periodo, incluida la segunda amarilla y el alargue. |
| `test_official_results.py` | Resultados oficiales de béisbol. |
| `test_predictor.py` | Cálculo de probabilidades (referencia histórica). |
| `test_public_football_client.py` | Fuente pública de fútbol. |
| `test_record_predictor.py` | Modelo basado en récord. |
| `test_records.py` | Registro manual: ligas, `event_id`, documento y servicio. |
| `test_repository.py` | Persistencia y liquidación. |
| `test_tennis_client.py` | Cliente de tenis. |
| `test_tennis_service.py` | Servicio de tenis. |
| `test_web_enrichment.py` | Parsers MLB y enriquecimiento. |

Las pruebas no requieren MongoDB ni red: usan dobles de prueba para los
clientes externos.
# Rankings

Las pruebas del recurso deben cubrir lotes, validaciones, idempotencia,
versionado, referencias opcionales/exactas, orden de filas y consultas de solo
lectura. Para comprobar los contratos OpenAPI ejecuta
`python scripts/generate_openapi.py --check`.
