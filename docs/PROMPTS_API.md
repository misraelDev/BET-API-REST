# API de prompts para analistas

La biblioteca administra prompts versionados en la colección MongoDB `prompts`.
Cada `prompt_id` es una identidad lógica independiente y cada revisión es
inmutable; publicar una mejora crea una versión nueva. Las rutas históricas
`/{sport}/{prompt_type}` se conservan para `analysis` y `evaluation`, y el
registro genérico permite agregar modelos analíticos especializados sin cambiar
el código, por ejemplo `football.first_goal_model`.

Contrato desplegado: `https://start-bet-api-rest.xzpbpr.easypanel.host/openapi.json`
(al desplegar este cambio, versión de API `1.9.0`). El contrato aislado está en
`openapi/prompts.yaml`.

## Identidad genérica `prompt_id`

Un `prompt_id` tiene el formato `<sport>.<nombre>` y solo usa minúsculas,
números y guiones bajos en cada segmento:

```text
football.analysis
football.evaluation
football.first_goal_model
football.first_goal_evaluation
```

El primer segmento identifica el deporte y el resto el nombre del prompt. No es
necesario publicar un tipo nuevo en el código: basta con elegir un `prompt_id`
nuevo.

### Consultar la versión vigente o una exacta

```http
GET /api/v1/prompts/football.first_goal_model
GET /api/v1/prompts/football.first_goal_model?version=2
GET /api/v1/prompts/football.first_goal_model?version_id=9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f
GET /api/v1/prompts/football.first_goal_model/versions
```

Sin `version` ni `version_id` devuelve la revisión vigente. El historial es
ascendente e incluye todas las revisiones inmutables. La respuesta contiene
`prompt_id`, `sport`, `prompt_type`, `version`, `version_id`, `prompt`,
`is_current`, `supersedes_version_id`, `author` y `change_summary`.

### Publicar una revisión genérica

```http
POST /api/v1/prompts/football.first_goal_model
Content-Type: application/json
```

```json
{
  "base_version_id": null,
  "prompt": "Contenido completo del prompt del modelo de primer gol...",
  "author": "ana.garcia",
  "change_summary": "Versión inicial del modelo de primer gol."
}
```

Para una mejora, consulta primero la versión vigente y envía su `version_id` en
`base_version_id`. Si otra persona publicó entre la consulta y el `POST`, la API
responde `409`; vuelve a consultar, integra los cambios y reintenta. No existe
`PUT` para sobrescribir una revisión.

### Compatibilidad con las rutas históricas

Las rutas siguientes siguen funcionando sin cambios y comparten el mismo
almacenamiento:

```http
GET  /api/v1/prompts/football/analysis
GET  /api/v1/prompts/football/analysis/versions
POST /api/v1/prompts/football/analysis
```

`analysis` y `evaluation` son historiales separados. El cuerpo incluye
`prompt_id` (por ejemplo `football.analysis`), `version`, `version_id`, `prompt`,
`is_current`, `supersedes_version_id`, `author` y `change_summary`.

Al comenzar cada ejecución, resuelve la versión vigente una sola vez y conserva
su `version_id` durante toda la ejecución. Si se publica una revisión mientras
el análisis está en curso, sigue usando y registrando la versión ya resuelta.
En los endpoints de registro se envía el `version_id`, y la API valida que la
revisión exista para ese deporte y tipo antes de guardar la referencia.

Los registros guardan `analysis_prompt` con `prompt_id`, `version` y
`version_id`. Las evaluaciones guardan `evaluation_prompt` con esos mismos
campos. `method_version` (o `model_version` en registros manuales) identifica
el método y no es una versión del prompt. Los registros históricos sin
referencia comprobable la mantienen ausente; no se completa retrospectivamente.

## Rutas de registro y esquemas de referencia

El esquema compartido `PromptReference` devuelto en los registros es:

```json
{
  "prompt_id": "football.analysis",
  "version": 1,
  "version_id": "3be3ffee060a4f01b01057c32f5ae197"
}
```

- `POST /api/v1/football/predictions`: el cuerpo del lote lleva
  `analysis_prompt_id` (opcional; por defecto `football.analysis`) y
  `analysis_prompt_version_id` junto a `items`. Todas las selecciones del lote
  quedan fijadas a esa misma revisión exacta. Cada `items[]` conserva su propio
  `method_version`, que no debe confundirse con `analysis_prompt.version`; por
  ejemplo, el algoritmo puede ser `first_goal_v2` mientras el prompt es
  `football.first_goal_model`.
- `POST /api/v1/football/predictions/{prediction_id}/evaluations`: el cuerpo
  lleva el `version_id` del pronóstico evaluado, `evaluation_prompt_id`
  (opcional; por defecto `football.evaluation`) y
  `evaluation_prompt_version_id` del prompt usado.
- `POST /api/v1/records`: para los picks manuales de cualquier deporte, el
  cuerpo incluye `analysis_prompt_version_id`.

Ejemplo de lote con un prompt especializado:

```json
{
  "analysis_prompt_id": "football.first_goal_model",
  "analysis_prompt_version_id": "3be3ffee060a4f01b01057c32f5ae197",
  "items": [
    {
      "idempotency_key": "2026-10-24-liga-mx-736644-first-goal-home",
      "event_id": 736644,
      "match_date": "2026-10-24",
      "league": "liga_mx",
      "home_team": "Pumas UNAM",
      "away_team": "Necaxa",
      "market": "first_team_to_score",
      "period": "full_time",
      "selection": "home",
      "probability": 52.0,
      "confidence": 4,
      "rationale": "El local genera más llegadas y anota primero.",
      "sources": [{"name": "ESPN"}],
      "analyst": "ana.garcia",
      "method_version": "first_goal_v2",
      "forecast_group_id": "grp-first-goal-736644"
    }
  ]
}
```

Ejemplo de evaluación:

```json
{
  "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
  "evaluation_prompt_id": "football.first_goal_evaluation",
  "evaluation_prompt_version_id": "90fcd2406d3e4cb2bea14502e1247311",
  "analyst": "ana.garcia",
  "diagnosis": "La selección se cumplió según el resultado final verificado.",
  "learnings": ["Conservar el criterio de evaluación por mercado."],
  "sources": [{"name": "ESPN"}]
}
```

El OpenAPI desplegado contiene los modelos completos de petición y respuesta;
los registros devuelven la referencia anidada `analysis_prompt` o
`evaluation_prompt`. La versión de método sigue en `method_version` y no se
autocompleta ni se sobrescribe con datos del prompt.

## Grupo de primer equipo en anotar

El mercado `first_team_to_score` admite agrupar las tres selecciones
(`home`, `away`, `none`) bajo el mismo `forecast_group_id`. El analista envía
las tres probabilidades; la API solo valida y almacena, no calcula ni ordena
pronósticos.

Reglas de validación:

- El grupo debe contener exactamente las selecciones `home`, `away` y `none`.
- Las tres deben referirse al mismo `event_id` y al mismo `period`.
- Las probabilidades deben sumar `100%` (tolerancia de `0.01` por redondeo).
- `forecast_group_id` solo se acepta en `first_team_to_score`.
- Cada selección sigue siendo un documento versionado independiente y conserva
  su propio `prediction_id`, `probability` y `method_version`.

El campo se devuelve en los pronósticos y puede usarse como filtro:

```http
GET /api/v1/football/predictions?forecast_group_id=grp-first-goal-736644
```

## Instantánea del modelo

Cada pronóstico puede incluir `model_snapshot`, una estructura opcional para
guardar las entradas y salidas exactas que produjeron la selección. Es
independiente de `method_version` y de la referencia del prompt.

```json
{
  "model_name": "first_goal",
  "model_version": "first_goal_v2",
  "generated_at": "2026-10-24T10:00:00-06:00",
  "queried_at": "2026-10-24T10:00:00-06:00",
  "lambdas": {"home": 1.42, "away": 0.87},
  "probabilities": {"home": 52.0, "away": 31.0, "none": 17.0},
  "intervals": {
    "home": {"lower": 46.0, "upper": 58.0, "confidence": 0.9}
  },
  "layer_contributions": {"attack": 0.61, "defense": 0.39},
  "odds": {"home": 1.9, "away": 3.4, "none": 12.0},
  "sources": [{"name": "ESPN"}],
  "missing_data": ["lineups"],
  "metadata": {}
}
```

Las fechas se guardan en UTC; `probabilities` se valida entre 0 y 100. El campo
es opcional para no alterar registros existentes. Los registros históricos sin
instantánea permanecen sin ella.

## Publicar una revisión

Para registrar la primera versión, envía `base_version_id: null`:

```json
{
  "base_version_id": null,
  "prompt": "Contenido completo del prompt...",
  "author": "ana.garcia",
  "change_summary": "Versión inicial del análisis de fútbol."
}
```

```http
POST /api/v1/prompts/football/analysis
Content-Type: application/json
```

Para una mejora, primero consulta la versión actual y copia su `version_id` a
`base_version_id`. El `POST` crea la siguiente revisión y conserva la anterior.
Si alguien publicó entre la consulta y el `POST`, la API responde `409`; vuelve
a consultar, integra los cambios y reintenta. No existe `PUT` para sobrescribir.

## Instrucciones a los analistas

- Para un análisis nuevo: “Usa la última versión del prompt de `football` tipo
  `analysis`”. La API devuelve esa revisión y el analista debe informar su
  `version_id` en el reporte.
- Para evaluar: “Usa la versión `<version_id>` del prompt `football` tipo
  `evaluation`”. La revisión es exacta y no se sustituye por la vigente.
- Los prompts de los otros deportes siguen los mismos recursos con `nba`,
  `baseball` o `tennis`.
- Los prompts iniciales en `promt/` son candidatos legibles en Git; no se
  insertan automáticamente en Mongo. Deben publicarse explícitamente con el
  `POST` inicial.

## Seguridad

El `POST` no tiene autenticación por decisión del proyecto. Mientras siga así,
no guardes credenciales en el prompt; limita el acceso de escritura en el proxy,
firewall o red privada. Cualquier cliente que alcance el endpoint puede publicar
una nueva versión vigente.

## Tipos de respuesta

- `200`: consulta correcta.
- `201`: publicación creada; reporta `version` y `version_id` devueltos.
- `404`: todavía no hay versión o no existe el ID solicitado.
- `409`: `base_version_id` obsoleto o conflicto de carrera.
- `422`: datos inválidos.
- `503`: MongoDB no disponible.
