# Biblioteca de prompts versionados

Los prompts se administran por la API y se guardan en la colección MongoDB
`prompts`. Esta carpeta mantiene contenido legible para revisión y publicación;
no es la fuente que el analista debe asumir vigente.

Cada deporte tiene dos tipos independientes:

- `analysis`: análisis y registro de pronósticos nuevos.
- `evaluation`: revisión posterior de pronósticos ya guardados.

Deportes contemplados por el modelo: `football`, `nba`, `baseball` y `tennis`.
Cada carpeta tiene candidatos `analysis/v1.md` y `evaluation/v1.md`. El API
devuelve la última versión si no se especifica ninguna, o una revisión exacta
mediante `version_id`. Los archivos no se siembran automáticamente en Mongo:
hay que publicarlos explícitamente con el endpoint.

## Publicación

1. Consulta el prompt vigente en
   `GET /api/v1/prompts/{sport}/{prompt_type}`.
2. Publica la revisión completa con `POST` al mismo recurso, incluyendo el
   `base_version_id` que acabas de consultar.
3. Para la primera versión envía explícitamente `base_version_id: null`.
4. Conserva el `version_id` devuelto y anota el cambio. Las revisiones antiguas
   no se sobrescriben; un `409` indica que la base quedó obsoleta.

El endpoint todavía no tiene autenticación. No debe exponerse para escritura
sin protección adicional en el proxy/red de producción.
