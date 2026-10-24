# Prompts de fútbol

Se separan en `analysis` y `evaluation`; cada archivo `vN.md` representa una
revisión humana candidata. La versión operativa es la que devuelve el API, no
necesariamente el archivo con número más alto en Git.

| Tipo | Archivo inicial | Uso |
| --- | --- | --- |
| `analysis` | [`analysis/v1.md`](analysis/v1.md) | Analizar partidos y registrar picks cuando se solicite. |
| `evaluation` | [`evaluation/v1.md`](evaluation/v1.md) | Evaluar picks existentes usando su `version_id` exacto. |

El antiguo prompt combinado se conserva como
[`../football-legacy-combined.md`](../football-legacy-combined.md) para consulta;
no se debe ejecutar junto con los prompts separados.
