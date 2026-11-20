# Preparación y observación de inventarios en Partida en vivo

Implementación revisada el 25 de octubre de 2026. La pantalla y los overlays activos son Electron/React. No se modifican operaciones IPC ni se añaden llamadas a Riot.

## Reutilización y puntuación

`LivePreparationService` adapta `LiveRecommendationService`, `SynergyRecommendationService` y `RepositorioCampeones`. La afinidad mecánica, compatibilidad de clase, build observada, respuestas a amenazas, inversión en componentes y restricciones de inventario proceden del motor existente. Las cifras mostradas son su puntuación final, no porcentajes de victoria.

Los escudos se identifican a partir de efectos del inventario y de concesiones de escudo en el catálogo Riot local mediante `get_champion_data(download=False)`, reutilizando su caché. Destruir un escudo no se interpreta como concederlo. Los perfiles de asesino aportan una señal estimada de ráfaga. Ambas señales usan la misma bonificación contextual existente para contramedidas; no se afirman daño medido ni enfriamientos disponibles.

La variante es Esmeralda+ para el campeón y rol observados. Si hay una página local con la misma piedra angular equipada, se selecciona su build y su orden de habilidades; la coincidencia de runas secundarias y muestra desempata. Esa build utiliza las bonificaciones existentes por build observada; no hay un segundo sistema de puntuación de runas. Sin una variante aplicable se conserva el perfil del campeón y se declara no disponible el orden de habilidades. Los alias de campeón pasan por las identidades compartidas, incluidos MonkeyKing/Wukong y Nunu.

Un único executor acotado del monitor calcula hasta tres alternativas legales. El servicio y los catálogos se reutilizan. Inventarios normalizados, piedra angular/runas, rol, modo, bajas/muertes/asistencias rivales y tramo de cinco minutos invalidan la puntuación. Una respuesta de otro contexto o partida se descarta. No se copia todo el historial de snapshots para puntuar: se entrega el estado actual y los últimos objetivos pertinentes.

El oro no invalida la puntuación. Un recorrido barato de las recetas calcula para cada alternativa la compra de mayor coste asequible, descontando componentes por multiconjunto y comprobando huecos. Si no alcanza, muestra un objetivo de ahorro; sin oro conocido, no afirma asequibilidad. Una pila de consumibles ocupa un hueco. Con seis huecos se permiten combinaciones que consuman componentes existentes; no se rellenan tarjetas con tres elixires de puntuación fija ni con objetos incompatibles.

## Evidencia de tienda

`EnemyInventoryTracker` es una máquina de estados sin red, timers propios, dependencias UI ni eventos paralelos. Consume los inventarios de la respuesta `playerlist` que el monitor ya utiliza. Las claves internas reutilizan las del tracker; el renderer recibe identificadores opacos por participante y partida. Sin identidad estable o sin inventario válido, el contador queda desconocido.

La [documentación oficial de Live Client](https://developer.riotgames.com/docs/lol#game-client-api_live-client-data-api) no incluye un indicador de visibilidad en `playerlist`, una marca de frescura por inventario ni un evento de compra/Recall. Por tanto, una lectura de API no se interpreta como un avistamiento en el mapa. Una diferencia ordinaria en inventario es evidencia de compra recibida en esa lectura; no revela el instante real de compra, la acción Recall ni el momento de llegada a base. La interfaz y los tooltips explican esta limitación.

Se normalizan ID y cantidad sin considerar ranuras. Una compra ordinaria reinicia el contador. La retirada aislada no demuestra venta: puede ser consumo, transformación o caducidad. No reinicia. El catálogo del parche y excepciones explícitas conservan el contador para:

- Calzado ligeramente mágico (`2422`), aunque el enemigo no exponga la página completa de runas.
- La progresión de Atlas mundial y sus mejoras; también se reconocen las cadenas históricas cuando existen en el catálogo.
- Transformaciones automáticas de Lágrima, objetos no comprables, trinkets y mejoras sin coste de combinación.
- Forja de Ornn: una adquisición no se atribuye a base. Las mejoras de Ornn no comprables también quedan excluidas.

Una evolución de apoyo junto con una compra pagada sí reinicia el contador. Los objetos desconocidos, snapshots inválidos, lecturas duplicadas y cortes de telemetría no inventan visitas. Tras un corte se toma una nueva línea base sin atribuir la compra al momento de reconexión. El retroceso del reloj de Practice Tool y una nueva sesión reinician el estado.

El contador usa exclusivamente `gameTime`: última tienda inferida o primera observación API válida. Se actualiza con la cadencia existente de dos segundos; no extrapola con reloj de pared durante pausas o desconexiones. Los estados son neutral (<120 s), ámbar (120–239 s), rojo (>=240 s). Solo el retrato crítico anima; la animación se detiene al reiniciar, ocultar o perder telemetría y respeta movimiento reducido.

## Presentación y contrato

`LiveMatchPage` conserva la tarjeta del jugador, runas, comparación, eventos y postpartida. El bloque introductorio grande se retira. `LiveMatchStatus` consume la publicación existente en la barra de navegación. El panel derecho de cronología abarca recomendaciones y comparación; los paneles se apilan en anchos reducidos.

`LiveSnapshot` añade opcionalmente `recommendations`, `skillOrder` y `enemyShopTimers`. Se mantiene el contrato versión 1 y `overlay.recommendations`. Las imágenes siguen resolviéndose mediante `home.assets`/`meta.assets`; se incluyen los componentes sugeridos en la adquisición cacheada de recursos. Los componentes React se conservan mediante claves y memoización. No se añaden intervalos para los contadores.

Las publicaciones que solo cambian el reloj, los contadores o la hora de lectura no invalidan la presentación completa. Los contadores, CS/min y la última lectura se suscriben al evento existente de forma independiente; sus listeners se retiran al ocultar/desmontar la vista. Las estadísticas e inventarios sí actualizan la pantalla cuando cambian.

## Validación y límites

- Pruebas de dominio: primeras observaciones, compra, calzado automático, progresión de apoyo con/sin compra, Lágrima, reordenación, consumibles, Ornn, duplicados, datos incompletos, cortes, retroceso del reloj y cambio de partida.
- Pruebas del motor y runtime: mismo campeón, contexto de runas, habilidad por rol, puntuaciones reales, contramedidas, componentes propios, presupuesto, huecos, publicación desde el worker real, cambios solo de oro y rechazo de resultados obsoletos.
- `npm --prefix frontend run test:live-preparation`: Chromium real con datos/assets simulados, anchos 800/1024/1280/1600/1920, barra expandida/plegada, 72 celdas, cinco contadores, inventarios de seis objetos, ausencia de overflow, reset del pulso, movimiento reducido y conservación de las tarjetas.
- `npm --prefix frontend run test:live-timeline`: regresión real Chromium de cronología, actores torre/súbdito y runas.
- Proceso JSONL real en Windows: versión inválida rechazada, `live.snapshot` y bootstrap válidos; EOF cierra con código 0.

Las pruebas usan fixtures y el catálogo local; no demuestran frescura de inventarios ocultos, exactitud de visitas a base ni compatibilidad de una partida real en curso. La observación de Magical Footwear, transformaciones y reconexiones en League requiere validación con el juego. No se afirma una detección de Recall que la fuente no proporciona.

Resultados de esta ejecución:

- `npm --prefix frontend run test:live-preparation`: pasó en las diez combinaciones de ancho/barra lateral; comprobó también scroll independiente, posición del estado junto al breadcrumb, pulso normal/movimiento reducido y reset.
- `npm --prefix frontend run test:live-timeline`: pasó en 280/310/420/760 px.
- `node --test tests/electron_shutdown_coordinator.test.cjs`: **4 pasaron**.
- `npm --prefix frontend run build`: pasó TypeScript y Vite; persiste el aviso de chunk JavaScript mayor de 500 kB.
- `compileall` y `git diff --check`: pasaron; Git muestra avisos existentes de conversión LF/CRLF.
- Proceso Windows PID 87292: versión inválida rechazada; `live.snapshot` y `app.bootstrap` válidos; salida **0** tras EOF. Datos temporales separados, grabación automática y sonido desactivados durante la comprobación.

## Archivos de esta implementación

- Dominio: `app/services/live_preparation_service.py`, `enemy_inventory_tracker.py`, `live_recommendation_service.py`, `identidad_campeon.py`.
- Runtime: `backend/live_match.py`.
- Pantalla/estado/recursos: `frontend/src/pages/LiveMatchPage.tsx`, `App.tsx`, `liveFixtures.ts`, `frontend/src/components/LivePreparation.tsx`, `LiveMatchStatus.tsx`, `frontend/src/types/contracts.ts`, `frontend/src/main.tsx`, `frontend/src/live-preparation.css`.
- Pruebas: `tests/test_live_preparation.py`, `tests/test_live_match_runtime.py`, `frontend/scripts/test-live-preparation.mjs`, `check-live-preparation-layout.cjs`; comando nuevo en `frontend/package.json`.
- Arquitectura y contratos actuales: este documento y `docs/live-match.md`.
# Corrección de habilidades y reaparición enemiga (25-10-2026)

- Live Match normaliza las etiquetas de línea de Live Client y usa la misma variante persistida en `RepositorioCampeones` que prepara Análisis local. En Practice Tool, si la línea es desconocida, selecciona la línea analizada con mayor muestra y la muestra explícitamente. Cuando se reemplaza el documento del campeón, comprueba su revisión con `stat` como máximo cada 15 segundos y recalcula mediante el worker existente; no se añade consulta de red ni sondeo de partida.
- `playerlist` ya aporta `isDead` y el contador de muertes. El rastreador de inventario congela el tiempo al observar `isDead=true`, conserva la última lectura mientras el campeón está muerto y fija el nuevo origen en la primera lectura `isDead=false`. Si se perdió el estado muerto entre lecturas pero aumentaron las muertes, usa la primera lectura viva como origen. El estado de la interfaz es `Muerto` sin animación hasta esa transición. Los cambios de inventario durante la muerte quedan incorporados a la línea base sin inferir una compra adicional.
- Limitación: la API no expone un evento con marca temporal exacta de reaparición. La lectura viva posterior puede llegar hasta una cadencia de seguimiento después del respawn real, o más tarde tras una desconexión. La hora mostrada identifica la observación confirmada, no afirma el instante exacto del juego. Si falta `isDead` y no hay incremento fiable de muertes, el rastreador conserva la evidencia previa.
- Datos locales verificados: la variante Briar/Jungla instalada actualmente entrega 18 niveles y prioridad `WQE`, y el servicio que prepara Análisis local devuelve esa misma secuencia. La tabla de referencia indicada en la petición (`WQE` con otra distribución por niveles) difiere de la caché instalada; Live Match sigue el resultado real de Análisis local sin codificar niveles de Briar.
