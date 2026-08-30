# Solralol

Panel de control y overlay para League of Legends, escrito en Python con PySide6.

Lee la partida activa desde la Live Client Data API local de League, muestra
tarjetas de jugadores y un overlay flotante, consulta el historial de partidas
mediante la Riot API bajo demanda, y desde la incorporación más reciente
también **graba cada partida jugada localmente y la analiza**, cruzando esa
telemetría local con los datos oficiales de Riot (Match‑V5) cuando están
disponibles.

> ✅ **Actualización.** Se ha recibido `app/ui/main_window.py`, que no estaba
> en el primer export analizado. Todo este README y el HTML de documentación
> se han revisado y corregido contra el código real de esa ventana principal.
> Ya no hay contenido inferido: la navegación, los botones **Buscar Riot**,
> **Re‑sincronizar** y **Abrir análisis** (los tres botones a los que te
> referías con "analizar / re-analizar / ver"), y el resto del cableado de
> señales están documentados con precisión a partir del código real.


## 1. Qué hace la aplicación

La ventana principal (`app/ui/main_window.py`, clase `MainWindow`) organiza la
app en 5 pestañas de navegación (`Inicio`, `Análisis`, `Partida en vivo`,
`Partidas guardadas`, `Ajustes`), sobre un `QStackedWidget`, con un fondo
degradado propio (`Backdrop`, dibujado a mano con `QPainter`/`QRadialGradient`
en azul y rojo).

- **Inicio**: estado del cliente de League (tarjetas de métricas) y, en la
  misma página, la sección "Actividad reciente" con el buscador de historial
  (Riot ID `nombre#TAG`, botón de refresco, estado).
- **Análisis**: visor externo por campeón/rol/rango/región (LoLalytics,
  U.GG, LeagueOfGraphs) con bloqueador de anuncios propio.
- **Partida en vivo**: panel en vivo con tarjetas por jugador, mientras hay
  una partida de League activa (incluida la herramienta de práctica). Se
  activa solo cuando `LiveDataWorker` detecta partida.
- **Partidas guardadas**: lista de partidas grabadas localmente
  (`LiveMatchTracker`) con sus botones de sincronización/análisis (ver más
  abajo).
- **Ajustes**: Riot API key, Riot ID y regiones.
- **Overlay flotante**: una ventana aparte (`OverlayWindow`), con opacidad
  ajustable y modo "click‑through", que resume la misma información sobre el
  juego.
- **Grabación local de la partida (`LiveMatchTracker`)**: mientras juegas, la
  app toma una "foto" del estado de todos los jugadores cada pocos segundos y
  registra eventos de objetivos (dragón, barón, heraldo, torres,
  inhibidores). Al terminar la partida, esa sesión se guarda en
  `~/.solralol/live_match_sessions.json`.
- **Sincronización con Riot (`PostgameSyncService`)**: una vez la partida ha
  terminado, la sesión grabada localmente puede cotejarse con la partida real
  en los servidores de Riot (Match‑V5 + Timeline). Si Riot ya la tiene
  procesada, la sesión se enriquece con estadísticas oficiales (KDA exacto,
  oro, daño, visión, build final, runas, resultado) y con los eventos
  oficiales de la timeline.
- **Análisis LIVE / postpartida (`LiveMatchAnalysisDialog`)**: una ventana de
  análisis por partida, organizada en pestañas por rol (TOP, JUNGLA, MID,
  BOT, SOPORTE), que compara a tu jugador contra su rival directo de calle:
  gráficas de evolución (oro, daño, etc.), panel de objetos, panel de runas,
  cronología de eventos y una lista de "logros" automáticos de la partida
  (ganar el early/mid/late, full AD/AP, full letalidad, etc.). Se puede abrir
  tanto **mientras la partida sigue en curso** (botón "Abrir análisis LIVE"
  en la pestaña Partida en vivo, que se va actualizando solo) como
  **después**, desde Partidas guardadas.
- **Historial de partidas vía Riot API**: bajo demanda (nunca en segundo
  plano ni por temporizador), consulta tus últimas partidas, con caché local
  y control de rate limit (HTTP 429).
- **Inspector de partidas (`MatchInspectorDialog`)**: detalle postpartida de
  una entrada del historial, con ambos equipos, objetivos y build final.
- **Ajustes**: guarda la Riot API key y las preferencias del usuario en
  `~/.solralol/settings.json`.

## 2. Requisitos

- Windows con League of Legends instalado (la Live Client Data API sólo
  existe mientras hay una partida o la herramienta de práctica activa).
- Python 3.10 o superior.
- Dependencias (`requirements.txt`): `requests`, `urllib3`, `PySide6`,
  `keyboard`.
  - `keyboard` está en `requirements.txt` pero **no se usa en ningún archivo
    del proyecto** en este export (ver `LIMPIEZA.txt`). Puede ser un
    resto de una función de atajos de teclado no implementada, o puede
    quitarse si no se va a usar.
- Para el visor de Análisis y para los diálogos de análisis debe estar
  disponible `PySide6.QtWebEngineWidgets` / `PySide6.QtWebEngineCore`.
- Una Riot API key propia (desarrollador o de producción) para el historial y
  la sincronización postpartida. Sin ella, la app sigue funcionando en modo
  "solo LIVE" (sin datos oficiales de Riot).

## 3. Puesta en marcha

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

El primer arranque descarga el catálogo de objetos de Data Dragon
(`data_dragon.load_item_catalog`) e imprime la versión de parche detectada
antes de abrir la ventana principal.

Para comprobar que un archivo modificado sigue siendo sintácticamente válido:

```powershell
python -m py_compile app\services\<archivo>.py
python -m py_compile app\ui\<archivo>.py
```

> La API local de League usa un certificado autofirmado; por eso las
> peticiones se hacen con `verify=False` y se silencian los avisos de
> `urllib3.exceptions.InsecureRequestWarning` al importar los módulos que
> hablan con `127.0.0.1:2999`.

## 4. Estructura real del proyecto (según el export analizado)

```
Solralol/
├── main.py                      Punto de entrada (QApplication + MainWindow)
├── data_dragon.py                Catálogo de objetos/campeones de Data Dragon (uso a nivel de app, no Qt)
├── riot_live.py                  Cliente LiveClient independiente, NO usado por la app (ver LIMPIEZA.txt)
├── riot_api.py                   Vacío, sin uso (ver LIMPIEZA.txt)
├── analyzer.py                   Vacío, sin uso (ver LIMPIEZA.txt)
├── config.json                   Vacío; la configuración real vive en ~/.solralol/settings.json
├── debug_cs.py                   Script manual de depuración (CS/scores del jugador local vía riot_live.py)
├── debug_enemy_runes.py          Script manual de depuración (runas del equipo rival vía riot_live.py)
├── test_endpoints.py             Script manual para probar endpoints de la Live Client Data API
├── reorganize_project.ps1        Script histórico de reorganización de carpetas (ya aplicado, desactualizado)
├── requirements.txt
├── Solralol_Documentacion1_0_0.html   Documentación HTML previa (sustituida por la nueva, ver más abajo)
├── app/
│   ├── models/
│   │   └── game_types.py         Vacío, reservado para tipados futuros
│   ├── services/
│   │   ├── game_service.py               Lectura de la Live Client Data API y snapshot normalizado
│   │   ├── live_data_worker.py           Worker en QThread que usa GameService + LiveMatchTracker (EN USO)
│   │   ├── live_data_worker_live_analysis.py   Variante casi idéntica, NO referenciada (ver LIMPIEZA.txt)
│   │   ├── "live_data_worker copy.py"    Copia de seguridad accidental, código de LiveMatchTracker antiguo (ver LIMPIEZA.txt)
│   │   ├── live_match_tracker.py         Graba la telemetría de la partida en curso y la persiste al terminar
│   │   ├── live_analysis_models_and_calculator.py   Cálculo de stats derivadas y "logros" de la partida
│   │   ├── postgame_sync_service.py      Empareja la sesión LIVE con la partida real de Riot (Match-V5)
│   │   ├── postgame_sync_worker.py       Ejecuta la sincronización anterior en un QThread
│   │   ├── riot_api_service.py           Cliente Riot API (Account-V1, Match-V5, resúmenes y detalle)
│   │   ├── riotlive.py                   Otro cliente LiveClient duplicado, NO usado (ver LIMPIEZA.txt)
│   │   ├── match_history_cache.py        Caché en disco de cuentas/partidas + cooldown de rate limit
│   │   ├── match_history_worker.py       Descarga historial/detalle en un QThread
│   │   ├── game_calculator.py            KDA, valor de inventario, stats de objetos, runas
│   │   ├── data_dragon_assets.py         Descarga asíncrona (Qt) de iconos de campeón/objeto con caché
│   │   └── settings_service.py           Carga/guarda ajustes y Riot API key en ~/.solralol/settings.json
│   ├── ui/
│   │   ├── main_window.py                Ventana principal: navegación, workers, historial, análisis, overlay
│   │   ├── control_window.py             Ventana principal de una arquitectura anterior (SolralolWindow); main_window.py NO la importa (ver LIMPIEZA.txt)
│   │   ├── champion_card.py              Tarjeta visual de un jugador (usada por main_window.py)
│   │   ├── inventory.py                  Construcción de los slots de inventario/trinket (usada por champion_card.py)
│   │   ├── overlay_window.py             Ventana overlay flotante (usada por main_window.py)
│   │   ├── styles.py                     Hoja de estilos Qt (QSS) del panel (usada por main_window.py)
│   │   ├── live_match_analysis_dialog.py Diálogo de análisis LIVE/postpartida por rol
│   │   └── match_inspector_dialog.py     Diálogo de detalle postpartida del historial (usado por main_window.py)
│   └── utils/
│       └── cache.py               Vacío, reservado
└── web/
    ├── app.js, index.html, styles.css   Los tres archivos están vacíos y no se usan (ver LIMPIEZA.txt)
```

La tabla completa de responsabilidades por archivo está en el HTML de
documentación (`Solralol_Documentacion.html`), sección **Estructura del
proyecto**.

## 5. Flujo de datos

### 5.1 Partida en vivo

```
League (127.0.0.1:2999) → GameService → LiveDataWorker (QThread)
        → señal snapshot_ready → hilo principal → tarjetas / overlay
```

En paralelo, `LiveDataWorker` mantiene un `LiveMatchTracker` que, cada vez
que llega un snapshot nuevo:

1. Indexa a todos los jugadores (aliados/enemigos, rol, nombre, campeón).
2. Registra un punto de la serie temporal (oro estimado, daño, CS, objetos,
   estadísticas de vida) para cada jugador.
3. Detecta eventos exactos de objetivos (dragón, barón, heraldo, torres,
   inhibidores) para no duplicarlos entre lecturas.
4. Emite la sesión LIVE en curso (`live_analysis_ready`) para que la interfaz
   pueda mostrar el análisis mientras la partida sigue activa.

Cuando `LiveDataWorker` detecta que League ha dejado de responder (partida
terminada) o que ha empezado una partida distinta, cierra la sesión anterior
con `LiveMatchTracker.finish()`, que la deja persistida en
`~/.solralol/live_match_sessions.json` con estado `final_sync.status =
"live_only"`.

### 5.2 Sincronización postpartida con Riot (función nueva)

```
Sesión LIVE finalizada → PostgameSyncWorker (QThread) → PostgameSyncService
        → RiotApiService (Match-V5 + Timeline) → sesión enriquecida
        → señal sync_ready → LiveMatchAnalysisDialog
```

`PostgameSyncService.sync_session(session)`:

1. Comprueba que hay API key, Riot ID (nombre#tag) y que la sesión tiene un
   `local_player_key` (si no, devuelve la sesión tal cual con
   `final_sync.status = "live_only"`).
2. Resuelve el PUUID del jugador (Account‑V1) y pide sus últimas partidas
   (Match‑V5, hasta 10 candidatas).
3. Para cada partida candidata, calcula una puntuación de coincidencia
   comparando campeón jugado, hora de inicio (tolerancia ±12&nbsp;min) y
   duración (tolerancia ±4&nbsp;min); se queda con la de menor diferencia.
   - Si Riot aún no tiene la partida procesada, o ninguna candidata encaja,
     la sesión queda en estado `"pending"` (se puede reintentar más tarde:
     de ahí el botón **Re‑analizar**).
   - Si Riot responde con un error controlado (`RiotApiError`), un 404/429
     se trata como `"pending"`; cualquier otro error queda como `"failed"`.
4. Si encuentra una coincidencia, descarga la timeline de esa partida y
   fusiona (`_merge_riot_data`) los datos oficiales de cada jugador
   (KDA, CS, oro, daño, visión, build final de hasta 7 objetos, runas,
   hechizos de invocador, resultado) en la sesión, sustituye los eventos
   estimados en vivo por los eventos oficiales de la timeline, y marca
   `final_sync.status = "synced"`.

Los cuatro estados posibles de `session["final_sync"]["status"]` son:
`live_only`, `pending`, `synced` y `failed`. Estos estados son, con toda
probabilidad, los que determinan qué botón se muestra para cada partida
grabada (ver aviso sobre `main_window.py` más abajo).

### 5.3 Diálogo de análisis (`LiveMatchAnalysisDialog`)

Recibe una sesión (LIVE o ya sincronizada), un `DataDragonAssetService` y el
catálogo de objetos. Al abrirse:

1. Calcula y adjunta "logros" (`attach_achievements`) a cada jugador:
   victoria, ganar early/mid/late (comparando oro estimado a los minutos 15
   y 30 y al final contra el rival de calle), builds ofensivas/defensivas
   notables (full AD ≥300, full AP ≥400, ≥150 armadura o RM, ≥3000 de vida
   extra, ≥50% de crítico, ≥25% de robo de vida, antiheal, letalidad y full
   letalidad ≥100).
2. Construye 5 pestañas, una por rol (`TOP`, `JUNGLE`, `MIDDLE`, `BOTTOM`,
   `UTILITY`), cada una comparando al aliado y al enemigo de esa calle
   (`lane_matchups` de la sesión).
3. Por cada jugador de la calle activa muestra: cabecera (campeón, Riot ID,
   KDA), runas, panel de métricas (con `calculate_item_stats` /
   `calculate_post_stats`), inventario final, gráficas de evolución
   (`VersusChart`, dibujadas a mano con `QPainter` sobre oro/daño a lo largo
   del tiempo) y una cronología de eventos filtrable por calle o global.

## 6. Botones "Analizar", "Re‑analizar" y "Ver" — comportamiento real confirmado

En **Partidas guardadas** (`create_saved_games_page` / `create_saved_game_row`
en `main_window.py`), cada partida grabada muestra su estado y hasta dos
botones, según `session["final_sync"]["status"]`:

| Estado (`final_sync.status`) | Texto mostrado al usuario | Botón(es) de la fila | Método que llama |
|---|---|---|---|
| `live_only` | "Solo telemetría LIVE" | **Buscar Riot** | `request_saved_session_sync(session_id)` |
| `pending` | "Pendiente de sincronización" | **Buscar Riot** | `request_saved_session_sync(session_id)` |
| `failed` | "Error al sincronizar" | **Buscar Riot** | `request_saved_session_sync(session_id)` |
| `synced` | "Sincronizada con Riot" | **Re-sincronizar** | `request_resync_session(session_id)` |
| *(cualquiera)* | — | **Abrir análisis** (siempre visible) | `open_saved_game_analysis(session)` |

Es decir, la correspondencia con la terminología de tu petición es:

- **"Analizar"** → botón **"Buscar Riot"**: llama a
  `request_saved_session_sync(session_id)`, que primero descarta partidas de
  práctica/tutorial/personalizadas (quedan en `live_only` para siempre, no se
  puede buscar en Riot), comprueba que hay API key y Riot ID configurados en
  Ajustes, marca la sesión como `pending` ("Buscando detalle y timeline en
  Riot…") y llama a `start_postgame_sync(session_id)`, que emite la señal
  `postgame_sync_requested` hacia `PostgameSyncWorker` (en su propio
  `QThread`). Cuando el worker responde (`sync_ready`/`receive_postgame_sync`
  o `sync_failed`/`receive_postgame_sync_error`), la sesión en disco se
  sustituye por la versión actualizada y la lista se refresca
  (`refresh_saved_games`).
- **"Re‑analizar"** → botón **"Re‑sincronizar"** (solo visible cuando
  `status == "synced"`): llama a `request_resync_session(session_id)`, que
  resetea manualmente `final_sync` a `live_only` ("Pendiente de
  re‑sincronización."), quita `official_events` de la sesión guardada, y
  vuelve a llamar a `request_saved_session_sync(session_id)` para repetir
  todo el proceso de arriba desde cero.
- **"Ver"** → botón **"Abrir análisis"** (siempre presente,
  independientemente del estado): llama a `open_saved_game_analysis(session)`,
  que simplemente crea un `LiveMatchAnalysisDialog(session,
  self.data_dragon_assets, self.item_catalog, self)` y lo muestra con
  `.exec()` (modal), sin tocar Riot para nada — usa la sesión tal cual está
  guardada en ese momento (con o sin datos oficiales, según haya sido
  sincronizada o no).

Además de estos tres, existe un cuarto botón, específico de la partida que
está ocurriendo ahora mismo, en la pestaña **Partida en vivo**:

- **"Abrir análisis LIVE"** (`open_live_analysis_button`): deshabilitado
  hasta que `LiveDataWorker` emite la primera sesión LIVE
  (`receive_live_analysis`). Al pulsarlo, `open_live_analysis()` reutiliza el
  diálogo si ya está abierto (lo trae al frente y lo refresca con
  `update_session`) o crea uno nuevo. Mientras la partida sigue activa, cada
  sesión LIVE nueva que llega (una vez por segundo, junto al snapshot del
  panel) se pasa automáticamente al diálogo abierto vía
  `dialog.update_session(session)`, así que se actualiza solo, sin que haga
  falta pulsar nada más.

Cuando la partida termina, `MainWindow` cierra la sesión
(`live_match_tracker.finish()`) y llama a `schedule_postgame_sync(session)`:
esta marca la sesión como `pending` ("Esperando a que Riot procese la
partida…") y programa, con `QTimer.singleShot(20_000, ...)`, una primera
sincronización automática 20 segundos después de terminar — sin que el
usuario tenga que pulsar "Buscar Riot" la primera vez. Si esa sincronización
automática no encuentra la partida en Riot todavía, queda en `pending` y es
cuando tiene sentido volver a pulsar el botón manualmente.

<details>
<summary>Detalle técnico adicional</summary>

- Las partidas de modo `PRACTICETOOL`, `PRACTICE`, `TUTORIAL`, `CUSTOM` o
  `CUSTOM_GAME` nunca se sincronizan con Riot (no existen en Match‑V5): el
  botón "Buscar Riot" las deja directamente en `live_only` con el mensaje
  "No disponible en Riot Match-V5: las partidas de práctica, tutorial y
  personalizadas conservan telemetría LIVE local."
- Todos los botones de sincronización se deshabilitan mientras
  `self.postgame_sync_in_progress` es `True`, para evitar lanzar dos
  sincronizaciones a la vez.
- `MainWindow.closeEvent` para tres `QThread` al cerrar la ventana: el de
  `LiveDataWorker` (`worker_thread`), el de `MatchHistoryWorker`
  (`history_thread`) y el de `PostgameSyncWorker`
  (`postgame_sync_thread`), con el mismo patrón `quit()` → `wait(5000)` →
  `terminate()` + `wait(2000)` si no responde a tiempo.
</details>

## 7. Reglas importantes que no deben romperse

Estas reglas ya estaban documentadas en la versión anterior del HTML y siguen
vigentes; se han verificado contra el código real de `main_window.py`:

1. **No añadir sondeos periódicos a la Riot API.** El único temporizador
   (`QTimer`) automático de sondeo continuo es `self.poll_timer`, que llama a
   `request_snapshot()` cada 1000&nbsp;ms para la Live Client Data API local.
   El historial (`MatchHistoryWorker`) solo se dispara por acción explícita
   del usuario (botón "Actualizar"). La sincronización postpartida
   (`PostgameSyncWorker`) solo se dispara una vez automáticamente 20&nbsp;s
   después de que termine cada partida (`schedule_postgame_sync` +
   `QTimer.singleShot`), o manualmente al pulsar "Buscar Riot" /
   "Re-sincronizar".
2. **Toda petición HTTP bloqueante va en un worker (`QThread`)**, nunca en el
   hilo de interfaz: así lo hacen `LiveDataWorker` (`worker_thread`),
   `MatchHistoryWorker` (`history_thread`) y `PostgameSyncWorker`
   (`postgame_sync_thread`), los tres creados en `MainWindow.__init__`.
3. **Reutilizar caché siempre que exista.** `MatchHistoryCache` guarda
   cuentas, resúmenes y detalles de partida por `match_id`; una partida
   detallada no debería descargarse dos veces. Ante HTTP 429 se respeta
   `Retry-After` o se bloquea localmente 120&nbsp;s.
4. **`DataDragonAssetService` se crea una única vez** (`self.data_dragon_assets`
   en `MainWindow.__init__`) y se pasa como parámetro a
   `MatchInspectorDialog` y `LiveMatchAnalysisDialog`; no debe instanciarse
   uno nuevo por jugador ni por partida.
5. **`verify=False` es intencional** para la API local de League (certificado
   autofirmado); no lo es para la Riot API real, que sí valida certificados.
6. **Las partidas de práctica/tutorial/custom nunca se sincronizan con
   Riot.** `request_saved_session_sync` las descarta explícitamente antes de
   llamar a la API porque no existen en Match‑V5.

## 8. Navegación de la ventana principal

`MainWindow` usa un `QStackedWidget` (`self.pages`) con 5 páginas, controladas
por botones de navegación exclusivos (`QButtonGroup`):

| # | Botón | Página | Contenido |
|---|---|---|---|
| 0 | Inicio | `create_home_page` | Estado del cliente de League (tarjetas de métricas) + sección "Actividad reciente" (buscador de historial por Riot ID). |
| 1 | Análisis | `create_analysis_page` | Visor web externo (LoLalytics / U.GG / LeagueOfGraphs) con bloqueador de anuncios. |
| 2 | Partida en vivo | `create_live_page` | Tarjetas por jugador + botón "Abrir análisis LIVE". Deshabilitada (`live_button.setEnabled(False)`) hasta que hay partida activa. |
| 3 | Partidas guardadas | `create_saved_games_page` | Lista de sesiones grabadas con los botones "Buscar Riot" / "Re-sincronizar" / "Abrir análisis". |
| 4 | Ajustes | `create_settings_page` | Riot API key, Riot ID, regiones. |

## 9. Documentación extensa

El detalle completo, método a método, de cada clase y servicio está en
[`Solralol_Documentacion.html`](./Solralol_Documentacion.html). Ábrelo en un
navegador; incluye buscador integrado en la barra lateral.