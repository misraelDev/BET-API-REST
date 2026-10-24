# API de prompts para analistas

La biblioteca administra prompts por deporte y tipo en la colección MongoDB
`prompts`. `analysis` y `evaluation` son historiales separados. Cada revisión es
inmutable; publicar una mejora crea una versión nueva.

Contrato desplegado: `https://start-bet-api-rest.xzpbpr.easypanel.host/openapi.json`
(al desplegar este cambio, versión de API `1.5.0`). El contrato aislado será
`openapi/prompts.yaml`.

## Consultar una versión

```http
GET /api/v1/prompts/football/analysis
```

Sin parámetros devuelve la versión vigente. Para pedir una versión concreta:

```http
GET /api/v1/prompts/football/analysis?version_id=9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f
GET /api/v1/prompts/football/analysis/versions
```

El cuerpo incluye `prompt_id` (identidad lógica estable, por ejemplo
`football.analysis`), `version`, `version_id` (revisión inmutable), `prompt`,
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
  `analysis_prompt_version_id` junto a `items`. Todas las selecciones del lote
  quedan fijadas a esa misma revisión. Cada `items[]` conserva su propio
  `method_version`, que no debe confundirse con `analysis_prompt.version`.
- `POST /api/v1/football/predictions/{prediction_id}/evaluations`: el cuerpo
  lleva el `version_id` del pronóstico evaluado y
  `evaluation_prompt_version_id` del prompt usado.
- `POST /api/v1/records`: para los picks manuales de cualquier deporte, el
  cuerpo incluye `analysis_prompt_version_id`.

Ejemplo de evaluación:

```json
{
  "version_id": "9a1c2e3f4b5d6a7c8e9f0a1b2c3d4e5f",
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
