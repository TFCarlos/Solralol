# Solralol

**Solralol** es una aplicación de escritorio (Windows) para acompañar tus partidas de
**League of Legends**. Construida con **Python 3.13 + PySide6 (Qt)**, combina varias
fuentes de datos en una sola interfaz:

| Fuente | Para qué sirve |
| --- | --- |
| **Live Client Data API** (`https://127.0.0.1:2999`) | Snapshots en vivo de la partida (oro, CS, KDA, objetivos, eventos). |
| **LCU API** (cliente local, *lockfile*) | Selección de campeones, importar runas/objetos/hechizos al cliente. |
| **Riot API** (oficial) | Historial de partidas, perfil, detalle de partida y sync post-partida. |
| **Gemini API** (Google AI Studio) | Análisis IA de partidas y re-análisis de campeones. |
| **Data Dragon / U.GG / OP.GG / Lolalytics** | Catálogos, iconos, winrates y builds. |

Incluye overlay en juego, grabación automática con ffmpeg, analizador de drafts,
análisis local de campeones/objetos, partidas guardadas sincronizadas con vídeo y
reproductor post-partida con timeline de objetivos.

---

## Índice

1. [Características principales](#1-características-principales)
2. [Arquitectura del proyecto](#2-arquitectura-del-proyecto)
3. [Requisitos](#3-requisitos)
4. [Instalación y ejecución](#4-instalación-y-ejecución)
5. [Configuración](#5-configuración)
6. [Guía de uso por pestaña](#6-guía-de-uso-por-pestaña)
7. [Flujos de datos](#7-flujos-de-datos)
8. [Modelo asíncrono (workers)](#8-modelo-asíncrono-workers)
9. [Servicios y endpoints externos](#9-servicios-y-endpoints-externos)
10. [Datos locales](#10-datos-locales)
11. [Build y empaquetado](#11-build-y-empaquetado)
12. [Scripts de desarrollo](#12-scripts-de-desarrollo)
13. [Solución de problemas](#13-solución-de-problemas)

---

## 1. Características principales

### Pestaña Inicio
- Tarjeta de bienvenida con estado de la conexión («League abierto · sin partida», «Esperando una partida»…).
- Tres métricas: **jugador**, **modo de partida** y **sesión** (se actualizan automáticamente).
- Configuración rápida de **Riot ID** (nombre de invocador + tag) con botón de refresco de historial.
- Accesos directos a **Análisis local**, **Herramienta de draft** y **análisis en vivo** (este último solo en partida).
- Gráfica de **elo/ranked (SoloQ)** reconstruida a partir del historial (cola 420, `calculate_elo_points`).

### Pestaña Análisis (`LocalAnalysisDialog`)
- Tres sub-pestañas: **Afinidad y gráficos**, **Editar campeones**, **Editar objetos**.
- Selector de campeón + estilo del campeón (AD/AP/verdadero, rol, curva de poder, fase de *spike*).
- Barras de composición de daño y gráfica radial de atributos.
- **Winrates desde U.GG**: actualizar un campeón o todos (`ChampionScraperWorker`, delay 0.8 s) + descarga de iconos de runas.
- Editor JSON de campeones y objetos con guardado en `data/champions_strict.json` / `data/legendary_items_strict.json`.
- **«Re-analizar con IA»**: `ChampionAIWorker` → servicio Gemini → atributos subjetivos del campeón.
- Recálculo matemático de sinergias de objetos (`synergy_multipliers`, `counter_weights`).
- Recomendaciones de afinidad: aliados, counters, buenos contra, objetos y runas.

### Pestaña Partida en vivo
- Se habilita automáticamente al detectar partida (la pestaña está deshabilitada fuera de juego).
- Abre **`LiveMatchAnalysisDialog`**: recomendaciones en vivo, tarjeta de amenazas y acción de IA.
- **«🤖 ANALIZAR PARTIDA CON IA»**: `MatchAIWorker` → `match_ai_analyzer_service` (modelos Gemini con *fallback*) + log de partida en `MatchLogService` (ver / copiar log).
- Overlay flotante con paneles **Oro / Alertas / Rivales**, opacidad, avance de alertas y sonidos (objetivo, dragón, compra enemiga).
- Grabación automática de la partida (si está activada) con marcadores de eventos.

### Pestaña Partidas guardadas
- Lista de sesiones grabadas/sincronizadas, cargada en segundo plano (JSON grandes + sidecars de vídeo).
- Por fila: **abrir análisis**, **sincronizar con Riot** (`request_saved_session_sync` → `PostgameSyncWorker`), **abrir vídeo** (reproductor) y **borrar sesión**.
- Refresco anti-flooding: si hay una carga en curso, la siguiente se marca pendiente y se repite una sola vez.

### Pestaña Grabaciones (`RecordingsPage`)
- Biblioteca de vídeos con sidecar `.json` (KDA, marcadores, eventos).
- Reproductor integrado (QMediaPlayer) con slider de posición y salto a marcadores.
- Tarjeta de KDA y resumen de marcadores (torres, dragones, barones, *kills*…).
- Acciones: refrescar, borrar, abrir carpeta, **detener grabación**, abrir ventana de replay.

### Pestaña Ajustes (4 tarjetas)
1. **API de Riot**: clave API + Riot ID + región (platform/base) con validación real (`save_and_validate_api_key` contra `platform-data`).
2. **Grabaciones**: auto-grabado, presets de calidad (1080p60 … 720p30), bitrate, audio, límite en GB, carpeta.
3. **Overlay**: paneles visibles (oro/alertas/rivales), opacidad, avance de alertas, modo solo-Tab, sonidos y volumen.
4. **IA Gemini**: clave con validación (`v1beta/models`), borrado y pasos para conseguirla gratis.

### Ventanas especiales
- **`DraftToolDialog`**: se abre **solo** al entrar en selección de campeones; analiza composiciones (daño, curva de poder, *spike*, bans) e importa **build, runas y hechizos** al cliente vía LCU.
- **`PostgameReplayWindow`**: vídeo + sidebar post-partida (`PostgameSidebar`) con desglose de daño/objetivos y salto a tiempo de juego.
- **`MatchInspectorDialog`**: inspector de una partida del historial (cabecera, tarjetas de equipo, objetos, posición, cola).
- **`OverlayWindow`**: overlay *click-through*; **`StartupWindow`**: arranque con catálogo de objetos.

## 2. Arquitectura del proyecto

```
Solralol/
├── main.py                  # Punto de entrada: StartupWindow → MainWindow, AppUserModelID
├── main.spec                # Spec de PyInstaller (build de dist/Solralol.exe)
├── _paths.py                # Rutas dev vs. empacado (~/.solralol/data, .bundle_version)
├── data_dragon.py           # Data Dragon: versions.json, catálogo de objetos (DD_BASE_URL)
├── run.bat                  # Ejecuta .venv\Scripts\python main.py
├── activate_env.bat         # Activa el entorno .venv en la consola
├── requirements.txt         # Dependencias (ver §3)
├── README.md / Solralol_Documentacion.html
├── data/                    # Datos locales
│   ├── champions_strict.json, legendary_items_strict.json, passive_rules.json
│   ├── champion_data/  champion_icons/  item_icons/  rune_icons/
│   ├── items.json  versions.json  settings.json  logs/  LogoApp.ico
├── app/
│   ├── models/ y utils/     # paquetes auxiliares (solo __init__ por ahora)
│   ├── services/            # Lógica de negocio y acceso a datos
│   │   ├── riot_api_service, game_service, lcu_service, live_match_tracker
│   │   ├── recording_service, postgame_sync_service, live_recommendation_service
│   │   ├── live_player_metrics_service, draft_analyzer_service, winrate_calculator
│   │   ├── champion_scraper_service, match_ai_analyzer_service, champion_ai_analyzer
│   │   ├── synergy_recommendation_service, item_synergy_calculator_service, playstyle_service
│   │   ├── overlay_alert_service, overlay_sound_service, tab_hotkey_service
│   │   ├── match_history_cache, match_log_service, settings_service
│   │   ├── game_calculator, synergy_math, data_dragon_assets
│   │   └── workers: live_data_worker, match_history_worker, postgame_sync_worker
│   └── ui/                  # Interfaz PySide6 (los workers de UI viven AQUÍ; incluye main_window.py)
│       ├── local_analysis_dialog, draft_tool_dialog, live_match_analysis_dialog
│       ├── postgame_replay_window, match_inspector_dialog, recordings_page
│       ├── overlay_window, startup_window, postgame_sidebar, live_timeline, styles
│       └── workers: async_task, live_analysis_task, champ_select_worker,
│                    match_ai_worker, champion_ai_worker, champion_scraper_worker,
│                    winrate_worker
├── web/, scratch/, build/, dist/       # Artefactos de desarrollo/build (§12)
└── riot_live.py, debug_*.py, test_fase1.py, scratch_test_parser.py  # Debug
```

> **Nota:** los workers **no** están en `app/workers/`: los de UI/genéricos están en
> **`app/ui/`** y los de datos pesados en **`app/services/`**.

### Mapa UI ↔ servicios (resumen)

| UI | Servicios con los que trabaja |
| --- | --- |
| `MainWindow` | `SettingsService`, `LiveDataWorker`/`GameService`, `LiveMatchTracker`, `RecordingService`+`RecordingLibrary`, `LCUService`, `TabHotkeyService`, `OverlayAlertService`, `OverlaySoundService`, `MatchHistoryWorker`, `PostgameSyncWorker`, `RiotApiService`, `MatchHistoryCache`, `WinrateCalculatorService` |
| `LocalAnalysisDialog` | `SynergyRecommendationService`, `ItemSynergyCalculator`, `PlaystyleService`, `ChampionScraperWorker`→`ChampionScraperService`, `ChampionAIWorker`→`ChampionAIAnalyzerService` |
| `LiveMatchAnalysisDialog` | `LiveRecommendationService` (señales de `LiveDataWorker`), `MatchAIWorker`→`MatchAIAnalyzerService`, `MatchLogService` |
| `DraftToolDialog` | `DraftAnalyzerService`, `LCUService` (runas/objetos/hechizos), `ChampSelectWorker` |
| `RecordingsPage` | `RecordingService`, `RecordingLibrary`, señales hacia `MainWindow` |
| `PostgameReplayWindow` | `PostgameSidebar`, `LiveTimeline`, `RecordingLibrary`, sync post-partida |
| `MatchInspectorDialog` | `RiotApiService` (detalle de partida), iconos Data Dragon |

## 3. Requisitos

- **Windows** (el overlay usa `user32`, la grabación usa ffmpeg; pensada para LoL en PC).
- **Python 3.13** (probado; 3.11+ debería funcionar).
- **League of Legends** instalado (para LCU y Live Client Data API).
- **ffmpeg** en el PATH o en una de las rutas que busca la app (ver §5).
- Clave de **Riot API** (developer portal) y, opcionalmente, clave **Gemini**.
- `pip install -r requirements.txt` — dependencias en uso real:
  `PySide6` (+ `shiboken6`), `requests`, `urllib3`, `beautifulsoup4`, `imageio-ffmpeg`.
  El resto (`PyQt5`, `customtkinter`, `pyqtgraph`, `numpy`, `keyboard`, `bottle`,
  `pywebview`, `pythonnet`…) es **legado**: no se importa dentro de `app/`.

---

## 4. Instalación y ejecución

### Opción A — scripts incluidos

```bat
:: 1) Crear entorno (solo la primera vez)
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

:: 2) Ejecutar
run.bat
```

- `run.bat` lanza `python main.py` con el intérprete de `.venv`.
- `activate_env.bat` abre una consola con el `.venv` activo para depurar a mano
  (`python main.py`, `python riot_live.py`, etc.).

### Opción B — manual

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

En VS Code hay tareas/lanzamientos en `.vscode/tasks.json` y `.vscode/launch.json`
(«Run Solralol») que ejecutan `main.py` con el intérprete del workspace.

**Arranque:** `main.py` muestra `StartupWindow`, carga el catálogo de objetos en un
worker (`load_catalog`), fija el *AppUserModelID* `Solralol.App` (icono correcto en la
barra de tareas) y construye `MainWindow` con `showMaximized()`.

---

## 5. Configuración

Todo se guarda en **`%USERPROFILE%\.solralol\settings.json`** vía `SettingsService`.

| Ajuste | Dónde | Detalle |
| --- | --- | --- |
| Clave API de Riot | Ajustes → «API de Riot» | **Guardar y comprobar** valida contra la API de plataforma. Necesaria para historial/detalle/sync. |
| Riot ID (nombre + tag) | Ajustes y Inicio | Se usa para el historial (`account-v1` por `gameName/tagLine`). |
| Región (platform/base) | Ajustes | p. ej. `euw1` / `europe` → `riot_platform_region` / `riot_account_region`. |
| Clave Gemini | Ajustes → «IA Gemini» | Validación con `v1beta/models` (`save_and_validate_gemini_api_key`). Botón «Eliminar clave Gemini». |
| Auto-grabado | Ajustes → Grabaciones | Activo ⇒ `start_match_recording` al detectar partida y `stop_match_recording` al terminar. |
| Calidad/bitrate/audio/límite GB | Ajustes → Grabaciones | `QUALITY_PRESETS` (1080p60…720p30), `BITRATE_PRESETS`, `AUDIO_MODES`, límite `LIMIT_MIN_GB`–`LIMIT_MAX_GB`. |
| Carpeta de grabaciones | Ajustes → Grabaciones | `default_recordings_dir()`; `RecordingLibrary` la lee para la biblioteca. |
| Overlay: paneles/opacidad/avance | Ajustes → Overlay | Paneles Oro/Alertas/Rivales, opacidad, `alert_lead_seconds`, modo **solo-Tab** (`TabHotkeyService`). |
| Sonidos del overlay | Ajustes → Overlay | Tipos (objetivo, dragón, compra enemiga) + volumen (`OverlaySoundService`, winsound). |

**ffmpeg**: `find_ffmpeg()` busca en el PATH, `~/.solralol/ffmpeg`, `C:\ffmpeg`,
`LocalAppData`, Chocolatey y el binario de `imageio-ffmpeg`. Sin ffmpeg no se puede
grabar (la app te avisa).

## 6. Guía de uso por pestaña

El sidebar de `MainWindow` usa índices fijos: **Inicio(0) · Análisis(1) ·
Partida en vivo(2) · Partidas guardadas(3) · Grabaciones(4) · Ajustes(5)**
(`HOME_PAGE_INDEX` … `SETTINGS_PAGE_INDEX`).

### 6.1 Inicio
1. Introduce tu **nombre de invocador** y **tag** (o hazlo en Ajustes) y guarda.
2. Pulsa **Refrescar historial**: `MatchHistoryWorker` carga partidas (con caché) y
   se rellenan filas, estado (`set_history_status`) y la gráfica SoloQ.
3. Usa los accesos: **Abrir análisis local**, **Abrir herramienta de draft**
   (también disponible sin draft para previsualizar) y **Abrir análisis en vivo**
   (solo habilitado con partida detectada).
4. Las métricas Jugador/Modo/Sesión se actualizan solas con los snapshots.

### 6.2 Análisis (local)
1. Elige un campeón en el combo (estilo, barras de daño y curva se recalculan).
2. **Winrates**: «Actualizar winrate» (campeón) o «Actualizar todos» →
   `ChampionScraperWorker` raspa U.GG con delay 0.8 s y descarga iconos de runas.
3. **Editar campeones**: modifica el JSON, «Guardar campeón» o
   **«Re-analizar con IA»** (Gemini reescribe los atributos subjetivos).
4. **Editar objetos**: editar nombre/descripción, «Recalcular sinergias del objeto»
   o «Recalcular todos los objetos» (`ItemSynergyCalculator`), «Guardar objeto».
5. Pestaña **Afinidad**: recomendaciones de aliados/counters/objetos/runas
   (`SynergyRecommendationService` + `PlaystyleService`).

### 6.3 Partida en vivo
1. Entra en una partida: la pestaña se habilita y se registran snapshots cada ~2 s
   (`LiveMatchTracker`, muestreo `SAMPLE_INTERVAL`).
2. Se abre automáticamente **`LiveMatchAnalysisDialog`**: recomendaciones
   (`LiveRecommendationService.analyze`) y amenazas (`OverlayAlertService`).
3. Pulsa **«🤖 ANALIZAR PARTIDA CON IA»** → confirmación → `MatchAIWorker`
   (modelos Gemini con *fallback*) → resultado + log en `MatchLogService`
   (botones «📄 Ver Log de Partida» y «📋 Copiar Log»).
4. El **overlay** muestra oro/alertas/rivales; con modo solo-Tab aparece al pulsar Tab
   (`TabHotkeyService`). Los sonidos avisan de objetivos/dragón/compras enemigas.
5. Si el auto-grabado está activo, la grabación empieza sola y aparece en Grabaciones.

### 6.4 Partidas guardadas
1. Al terminar la partida, `finish_live_session` cierra la sesión, para la grabación
   y **`schedule_postgame_sync`** espera a que Riot procese el partido
   (`PostgameSyncWorker` → `postgame_sync_service`, ~12 s × 60 intentos).
2. «Actualizar» recarga la lista en worker (sesiones + vídeos + sidecars).
3. Por fila: **Abrir análisis**, **Sincronizar** (trae el desglose post-partida),
   **Abrir vídeo** (replay) o **Borrar**.

### 6.5 Grabaciones
1. Lista de vídeos con KDA y marcadores (torre, dragón, barón, *kill*…).
2. Selecciona un vídeo para reproducir; usa el slider o los marcadores para saltar.
3. Botones: refrescar, borrar, **abrir carpeta**, **detener grabación** (si está en
   curso) y **abrir ventana** (→ `PostgameReplayWindow` con sidebar post-partida).

### 6.6 Ajustes
Rellena las 4 tarjetas descritas en §5. Cada botón «Guardar y comprobar» valida la
clave en línea y guarda el resultado en `settings.json`.

---

## 7. Flujos de datos

### 7.1 Selección de campeones (LCU)
```
ChampSelectWorker (poll 1.5 s, lee lockfile LCU)
  → champ_select_started   → MainWindow abre DraftToolDialog (automático)
  → champ_select_updated   → dialog.update_from_lcu_session(session)
  → champ_select_ended     → cierra el diálogo y prepara navegación a «En vivo»
DraftToolDialog → DraftAnalyzerService (comps, daño, curva, spike, bans)
               → LCUService.import_rune_page / import_item_set / import_summoner_spells
```

### 7.2 Partida en vivo
```
GameService (https://127.0.0.1:2999/liveclientdata, cert autofirmado)
  → LiveDataWorker (QThread, ~2999 ms)
      ├─ snapshot_ready      → receive_snapshot → overlay, métricas, inicio de grabación
      ├─ live_analysis_ready → receive_live_analysis → LiveMatchAnalysisDialog + alertas
      └─ game_ended          → handle_game_ended → finish_live_session(reason)
                                 ├─ LiveMatchTracker.finish() → sesión JSON
                                 ├─ stop_match_recording() (+ marcadores de eventos)
                                 ├─ schedule_postgame_sync() → PostgameSyncWorker
                                 └─ refresh_saved_games()
```

### 7.3 Historial y perfil (Riot API)
```
refresh_history → history_requested → MatchHistoryWorker
  → RiotApiService (account-v1 → match-v5) + MatchHistoryCache (~/.solralol/…json, TTL)
  → history_ready → filas, KDA, cola 420, gráfica de elo (calculate_elo_points)
  → profile_requested → summoner/nivel/rango → home metrics
  → detail_requested  → MatchInspectorDialog (detalle enriquecido)
```

### 7.4 Análisis con IA (Gemini)
```
LiveMatchAnalysisDialog.start_ai_analysis → MatchAIWorker (hilo)
  → match_ai_analyzer_service.analyze_match(...)  # modelo con fallback:
     gemini-2.5-flash-lite → 2.5-flash → flash-latest → 2.0-flash-lite → 2.0-flash → 1.5-flash
  → MatchLogService.save_log(...)  (visible con «Ver Log de Partida»)
LocalAnalysisDialog «Re-analizar con IA» → ChampionAIWorker
  → champion_ai_analyzer_service (modelos 2.5-flash → 2.0-flash → 1.5-flash + fallback)
```

## 8. Modelo asíncrono (workers)

| Worker | Ubicación | Mecanismo | Señales / función |
| --- | --- | --- | --- |
| `AsyncTask` | `app/ui/async_task.py` | `QThreadPool` + `QRunnable` | Tarea genérica con callbacks. |
| `LiveAnalysisTask` | `app/ui/live_analysis_task.py` | `QThreadPool` | Ejecuta `LiveRecommendationService.analyze` sin bloquear la GUI. |
| `ChampSelectWorker` | `app/ui/champ_select_worker.py` | QTimer (1.5 s) | `champ_select_started/updated/ended` (LCU). |
| `MatchAIWorker` | `app/ui/match_ai_worker.py` | `QThread` | Análisis Gemini de la partida + log; `finished`/`error`. |
| `ChampionAIWorker` | `app/ui/champion_ai_worker.py` | `QThread` | Re-análisis IA de atributos del campeón. |
| `ChampionScraperWorker` | `app/ui/champion_scraper_worker.py` | `QThread` | Scrapeo U.GG (delay 0.8 s) + iconos de runas. |
| `WinrateUpdateWorker` | `app/ui/winrate_worker.py` | `QThread` | Recalcula winrates con `WinrateCalculatorService`. |
| `LiveDataWorker` | `app/services/live_data_worker.py` | `QThread` (moveToThread) | `snapshot_ready`, `live_analysis_ready`, `read_failed`, `game_ended` (~2999 ms). |
| `MatchHistoryWorker` | `app/services/match_history_worker.py` | `QThread` | `history_ready/failed`, `profile_ready/failed`, `detail_ready/failed`. |
| `PostgameSyncWorker` | `app/services/postgame_sync_worker.py` | `QThread` | `sync_ready/failed/progress` (espera procesamiento de Riot). |

Regla general: **nunca** se hacen peticiones de red, scraping, lectura de JSON grandes
ni procesamiento de vídeo en el hilo de GUI; todo pasa por señales Qt.

---

## 9. Servicios y endpoints externos

| Servicio | Endpoint / fuente | Uso |
| --- | --- | --- |
| Live Client Data API | `https://127.0.0.1:2999/liveclientdata` (`gamestats`, `allgamedata`, `eventdata`) | Snapshots y eventos en vivo (certificado autofirmado → `verify=False`). |
| LCU API | *lockfile* en `C:\…\Riot Games\League of Legends\lockfile` (también D:/E:/F:) | Champ select, `import_rune_page`, `import_item_set`, `import_summoner_spells`. |
| Riot API | `account-v1`, `match-v5`, plataforma (`platform-data`), rangos | Historial, perfil, detalle, sync post-partida; validación de clave. |
| Data Dragon | `https://ddragon.leagueoflegends.com/` (`versions.json`) | Catálogo de objetos e iconos (`data_dragon.py`, `data_dragon_assets.py`). |
| Gemini API | `https://generativelanguage.googleapis.com/v1beta/...` | `match_ai_analyzer_service` y `champion_ai_analyzer_service` (modelos con *fallback*). |
| U.GG / OP.GG / Lolalytics | webs públicas (HTML/JSON) | Winrates y builds (`champion_scraper_service`). |

---

## 10. Datos locales

| Ruta | Contenido |
| --- | --- |
| `%USERPROFILE%\.solralol\settings.json` | Ajustes (claves, overlay, grabación). |
| `%USERPROFILE%\.solralol\match_history_cache.json` | Caché de historial (versión 2 + TTL/cooldown). |
| `%USERPROFILE%\.solralol\` | Sesiones del tracker (`LiveMatchTracker`, máx. 50), logs de IA, `ffmpeg` opcional. |
| `data/` (repo) o `~/.solralol/data` (empaquetado) | `champions_strict.json`, `legendary_items_strict.json`, `passive_rules.json`, `items.json`, iconos y `LogoApp.ico`. |
| Carpeta de grabaciones | `.mp4` + sidecar `.json` (KDA, marcadores) gestionados por `RecordingLibrary`. |

`_paths.py` unifica ambas situaciones: en desarrollo usa `./data`; en el `.exe`
copia el bundle a `~/.solralol/data` si cambia `.bundle_version`.

## 11. Build y empaquetado

```bat
:: Con el .venv activo:
pyinstaller main.spec
:: → dist/Solralol.exe  (~260 MB en build previo)
```

Detalles de `main.spec`:
- **name**: `Solralol`, icono `data/LogoApp.ico`, `console=True` (útil para logs), `upx=True`.
- **datas**: carpeta `data/` completa.
- **hiddenimports**: `imageio_ffmpeg`, `PySide6.QtMultimedia/QtMultimediaWidgets`,
  `shiboken6`, `PySide6.QtWebEngine*`, `_paths`, `data_dragon` (evitan fallos al
  empaquetar vídeo y módulos importados de forma dinámica).
- Artefactos intermedios en `build/`; ejecutable final en `dist/`.
- `build/`, `dist/` y `__pycache__` están en `.gitignore`.

---

## 12. Scripts de desarrollo

| Archivo/carpeta | Propósito |
| --- | --- |
| `riot_live.py` | Prueba rápida de la Live Client Data API en consola. |
| `debug_cs.py`, `debug_enemy_runes.py` | Depuración de CS y runas enemigas. |
| `test_fase1.py`, `scratch_test_parser.py` | Pruebas de fases y parsers. |
| `data_dragon.py` | Módulo compartido: `versions.json`, `load_item_catalog()`. |
| `scratch/` | Pruebas sueltas (overlay, tracking, análisis…). |
| `web/`, `build/`, `dist/` | Artefactos: web auxiliar, build intermedio y ejecutable. |

No forman parte de la app; se ejecutan con `activate_env.bat` + `python <script>`.

---

## 13. Solución de problemas

| Síntoma | Causa probable | Solución |
| --- | --- | --- |
| «Partida en vivo» deshabilitada | No hay partida o no responde `127.0.0.1:2999` | Abre League y entra en partida. |
| No se abre el draft al entrar en champ select | LCU no accesible | Reinicia el cliente; comprueba el `lockfile` en la ruta de instalación. |
| Historial vacío / error 403 | Clave o Riot ID mal configurados | Ajustes → «Guardar y comprobar»; revisa nombre+tag y región. |
| Rate-limit de Riot | Demasiadas peticiones | `MatchHistoryCache` aplica TTL/cooldown; espera y reintenta. |
| No graba | Falta ffmpeg o carpeta inválida | Instala ffmpeg (o usa `imageio-ffmpeg`); revisa carpeta y límite GB. |
| IA no responde | Clave Gemini ausente/inválida o cuota | Ajustes → validar la clave; se prueban varios modelos con *fallback*. |
| Overlay no aparece / no es clicable | Modo solo-Tab u opacidad baja | Desactiva «solo-Tab», pulsa Tab o sube la opacidad. |
| Vídeo sin marcadores | Aún no hay sync post-partida | Pulsa «Sincronizar» en Partidas guardadas. |
| `.exe` no encuentra datos | Bundle desactualizado | Borra `~/.solralol/data` para que `_paths.py` lo recopie. |

---

**Solralol** · app de escritorio para League of Legends · Python + PySide6 ·
documentación extendida en [`Solralol_Documentacion.html`](./Solralol_Documentacion.html).





