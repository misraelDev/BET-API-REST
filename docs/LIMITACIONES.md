# Limitaciones

- El registro es manual: la API no calcula probabilidades, no estima cuotas y
  no propone picks. La calidad del registro depende de los datos que envíes.
- No hay endpoint de calendario. Los partidos y sus `event_id` se buscan en las
  fuentes públicas descritas en la [guía del analista](ANALISTA.md).
- Las fuentes públicas pueden cambiar su HTML o formato sin previo aviso; los
  parsers deterministas dejan de encontrar datos hasta que se ajusten.
- La liquidación depende de que la fuente publique el resultado final; hasta
  entonces los registros quedan pendientes.
- Sin `event_id` correcto no hay liquidación automática en fútbol, NBA ni
  tenis. En béisbol el id es sintético y `results/settle` solo cubre MLB.
- `POST /baseball/results/settle` consulta el calendario público de MLB. KBO
  solo aporta resultados oficiales vía `results/update`.
- `odds` y `stake` son informativos: no alteran las unidades liquidadas.
- El filtro `min_probability` depende de la probabilidad que envíes. Si omites
  `probability`, el registro no aparece en ese filtro.
- El filtro `hour` interpreta la hora en horario de México (UTC-6) y requiere
  que `kickoff` esté en ese mismo huso para coincidir.
- La caché de calendario (`CACHE_TTL_SECONDS`) puede retrasar hasta ese tiempo la
  actualización de partidos oficiales.

## Pronósticos de fútbol versionados

- La fuente de resultados y estadísticas es el resumen público de ESPN. Si ESPN
  no devuelve el partido, queda en `unmatched_event_ids` y la selección sigue
  `pendiente`.
- **Remates**: se usa `totalShots` de ESPN (todos los intentos que la fuente
  cuenta). `blockedShots` se publica aparte y **no** se suma. **Remates a
  puerta** usa `shotsOnTarget`. Cambios en la definición de ESPN cambian el
  número observado.
- **Tarjetas**: los eventos del partido son la fuente preferida porque el
  boxscore de ESPN no suma la segunda amarilla a `yellowCards`. Si no hay
  eventos de tarjetas, se usa el boxscore. Una segunda amarilla cuenta como
  amarilla + roja (2); una roja directa cuenta 1.
- Algunas competiciones publican `boxscore.teams` vacío. En ese caso
  `stats_reliable=false`, las tarjetas se toman de los eventos y córners o
  remates quedan sin dato (`no_evaluable`).
- Las plantillas se consideran completas solo si ambos equipos listan al menos
  11 jugadores. Con plantilla parcial no se deduce un cero para un jugador
  ausente: el mercado queda `no_evaluable`.
- Córners, remates y remates a puerta aceptan registro por periodo. Sin embargo,
  el parser integrado de ESPN hoy solo extrae estadísticas agregadas; los picks
  de 1T/2T quedan `no_evaluable` con motivo hasta que una fuente entregue datos
  verificables por periodo. Nunca se infiere una mitad del total del partido.
- En partidos con alargue o penales, `full_time` usa la regulación (primeros dos
  parciales). Córners y remates de esos partidos quedan `no_evaluable` porque la
  estadística incluye el tiempo extra. Las tarjetas se cuentan con los eventos
  de regulación.
- Asian handicap admite líneas de cuarto; las otras líneas son múltiplos de
  0.5. Se liquidan media ganancia y media pérdida. Las reglas nuevas usan
  `football-settlement-v2`; las liquidaciones antiguas conservan su versión.
- Saudi Pro League, Qatar Stars League, AFC Champions League Elite, AFC
  Champions League Two y UEFA Conference League están disponibles para
  registro, pero explícitamente sin liquidación automática verificada.
- `POST /api/v1/football/results/update` liquida como máximo 500 pronósticos
  vigentes por fecha en cada ejecución.
- La liquidación oficial no la hacen los endpoints del analista. La evaluación
  posterior es un diagnóstico separado y no modifica el pronóstico.
- No hay autenticación: cualquiera con acceso a la API puede registrar o
  evaluar. Antes de publicarla, usa HTTPS y un proxy con control de acceso.
- Quedan fuera de esta entrega las asistencias, los goleadores individuales y
  las porterías a cero.

## Documentos relacionados

- [Guía del analista](ANALISTA.md)
- [Arquitectura](ARQUITECTURA.md)
- [Persistencia](PERSISTENCIA.md)
