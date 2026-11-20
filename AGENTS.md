# Solralol: instrucciones para agentes

## Estado del proyecto

Solralol es un acompanante de League of Legends para Windows. La aplicación de producto usa Electron, React y TypeScript, con un backend Python separado por JSON Lines sobre stdio. No hay una interfaz de producto Python/Qt; `solralol_dev.py` es una herramienta de desarrollo opcional.

No autoriza commits Git. Mantener historia, grabaciones, preferencias y datos del usuario. Los refactors reversibles dentro del alcance no requieren aprobación. No declarar validación real de League, fullscreen, LCU, audio o hardware si solo se usaron fixtures.

## Stack y límites comprobados

- Frontend: Electron, React, TypeScript y Vite, bajo `frontend/`.
- Electron main (`frontend/electron/main/`) es dueño del ciclo de vida Python y de ventanas. El preload (`frontend/electron/preload/`) publica una API pequeña mediante `contextBridge`; renderer con `contextIsolation`, `sandbox` y `nodeIntegration: false`.
- Backend: Python en `backend/`, iniciado como proceso hijo. RPC JSON Lines sobre stdin/stdout; stdout contiene únicamente respuestas de protocolo y stderr diagnósticos. No abre puertos ni importa Qt.
- El contrato actual es versión 1. Operaciones permitidas: `app.bootstrap`, `champions.list`, `champions.analysis`, `settings.public`. Los contratos renderer están en `frontend/src/types/contracts.ts`; validación y despacho backend en `backend/` y allowlist IPC en main y preload.
- El backend reutiliza `RepositorioCampeones`, `rangos_campeones` y `SettingsService`. `settings.public` solo devuelve booleanos; no exponer claves.
- El código de reglas, datos e integraciones está en `app/services/`, `backend/`, `data/` y módulos raíz.

## Responsabilidades

- UI, navegación, animaciones, estado de presentación y reproducción visual: React/TypeScript. Usar solo `window.solralol` para operaciones del producto.
- Integraciones Riot/LCU/Live Client, scraping, normalización, analítica, recomendaciones, persistencia, grabación y coordinación de tareas: Python.
- Ventanas Electron, seguridad de IPC, proceso backend y recursos nativos: `frontend/electron/`.
- Contratos: tipos TypeScript documentados y esquemas validados en Python. Cambios incompatibles requieren aumentar versión del protocolo o mantener compatibilidad explícita.
- Archivos en `data/` y `~/.solralol/` son datos existentes; leer/migrar sin borrado implícito. No copiar credenciales al renderer.

## Estructura actual

- `frontend/src/pages/`: pantallas React actuales; `components/`, `hooks/`, `stores/`, `services/`, `overlays/` se añadirán al migrar necesidades concretas, evitando carpetas vacías.
- `frontend/src/types/`: contratos del renderer.
- `frontend/electron/main/`, `frontend/electron/preload/`: ciclo de vida/IPC y API aislada.
- `backend/application.py`: fachada de operaciones; `backend/protocol.py`: proceso JSONL; `backend/contracts.py`: envoltorios de protocolo.
- `app/services/`: servicios de dominio, integraciones y repositorios sin adaptadores de UI.
- `data/`: catálogos, metadatos, campeones y cachés existentes.
- `tests/`: pruebas automatizadas de backend, contratos y renderer.

## Desarrollo

Desde PowerShell en la raíz, instala una vez el entorno Python y las dependencias de frontend:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
cd ..
npm run dev
```

`npm run dev` desde la raíz coordina Vite y Electron sin build. Vite hace HMR de React; el proceso Electron administra el único backend Python y lo reinicia al cambiar archivos `.py` de `backend/`, `app/services/`, `_paths.py` o `data_dragon.py`. Cambios en main/preload relanzan Electron después de cerrar el backend. Al cerrar la ventana, los servicios de desarrollo terminan. Se puede ejecutar el mismo comando desde `frontend/` para comodidad. El intérprete predeterminado es `.venv\Scripts\python.exe`; `SOLRALOL_PYTHON` permite elegir otro.

`.venv\Scripts\python.exe solralol_dev.py` desde la raíz abre la herramienta de desarrollo opcional (requiere PySide6 en `requirements-dev.txt`). Sus botones inician Electron/Vite, solicitan reinicio manual del backend, ejecutan `pytest tests/` en un proceso cancelable y detienen solo los procesos que administra. El panel no se conecta a un backend externo ni reinicia procesos que no posee. Detecta el backend del proyecto ya activo antes de lanzar otro y avisa si pertenece a otro launcher. Para iniciar el backend solo, el panel usa `python -u -m backend.protocol` y su handshake JSONL.

En VS Code, F5 inicia el stack y conecta los depuradores del renderer React, Electron main y Python. Para habilitar el depurador Python instala `requirements-dev.txt`, que añade `debugpy`; `npm run dev:debug` ofrece el mismo modo desde una terminal. En modo debug, las herramientas escuchan solo en `127.0.0.1`: renderer Chromium en `9230`, Electron main en `9229` y debugpy en `5678`. `npm run build` y `npm run dist:win` desde la raíz delegan en los scripts existentes de `frontend/`; el segundo empaqueta el backend con PyInstaller y electron-builder. Las pruebas automatizadas residen en `tests/` y los checks del renderer en `frontend/scripts/`.

## Reglas de implementación

- UI nueva en React/TypeScript; lógica de aplicación en Python. El renderer no contiene scraping, claves, cálculo de recomendaciones, acceso a archivos, shell ni acceso directo a Riot/LCU.
- Añadir operaciones por contrato explícito, validación del método y parámetros en main/preload/backend, errores tipados, timeouts y cancelación si el trabajo lo requiere. No enviar objetos internos ilimitados ni errores con secretos.
- No importar PySide6/PyQt en `backend/` ni en `app/services/`.
- No bloquear procesos UI ni el loop asíncrono del backend con I/O o CPU intensiva. Elegir async I/O, threads o procesos según carga; limitar colas, cachés y trabajos en paralelo; descartar resultados obsoletos.
- Preferir cache/repositories existentes y actualizaciones incrementales. No añadir polling si eventos/suscripción o consulta bajo demanda sirven.
- No fabricar métricas, recomendaciones, cobertura, ni estados de integración. La UI debe distinguir no disponible, muestra parcial y error.
- Mantener compatibilidad y comportamiento de reglas existentes. No retirar una función de producto ni sus datos sin demostrar que el flujo actual la reemplaza.
- Usar los datos Data Dragon cacheados y resolver campeones mediante identificadores canónicos, no nombres frágiles.
- No añadir dependencias sin necesidad concreta. Mantener lockfile npm y versiones reproducibles.

## Seguridad y datos

- Electron debe conservar `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`; nunca exponer `ipcRenderer`, filesystem, `child_process` o canales IPC genéricos al renderer.
- El proceso Python es hijo privado de Electron y usa stdio; no abrir servidor de red local. Mantener stdout libre de logging. Validar JSON/tipos/tamaños y lista de operaciones.
- Secretos solo en el backend y almacenamiento ya usado por usuario. No registrar claves, lockfile de League, Riot ID/PUUID ni contenido privado de partidas.
- Mantener escrituras atómicas/versionadas. Caches descargables se distinguen de sesiones, settings y recordings; limpieza exige política concreta y segura.

## Flujo para nuevas funciones

1. Revisar `docs/architecture.md` y el código real antes de diseñar.
2. Localizar la implementación actual y sus pruebas de dominio, contrato y renderer.
3. Definir operación/evento, payload, errores, cancelación y límites; actualizar el contrato Python y TypeScript y las allowlists.
4. Implementar UI React reutilizable con estados de carga/vacío/parcial/error; actualizar una vista solo ante cambios relevantes.
5. Añadir pruebas de dominio, protocolo y componente/integración pertinentes; distinguir fixtures simulados de verificación con cliente/juego real.
6. Actualizar inventario, instrucciones y compatibilidad. Informar lo no validado.

## Performance y validación

Mantener pequeñas las respuestas y emitir deltas para telemetría frecuente. Evitar peticiones repetidas, parseo de archivos sin cambios, polling rápido, temporizadores ocultos y trabajos sin dueño/cancelación. Instrumentar latencias de RPC, consultas a proveedores, startup y eventos antes de afirmar mejoras. Para grabación medir overhead en juego; pruebas de escritorio no demuestran compatibilidad con League fullscreen.

Cuando el usuario pida verificar, probar protocolo válido/malformado, ciclo de vida/crash, build frontend, migración de datos y flujos funcionales. Para LCU, overlays, DXGI/FFmpeg, audio, fullscreen y Riot real, informar explícitamente si solo hubo simulación. Documentar comandos reales y resultados. No declarar migración acabada mientras queden capacidades esenciales desconectadas o el empaquetado sin verificar.

## Prohibido

- Reintroducir dependencias Qt en servicios del nuevo backend.
- Implementar scraping o analítica en React o duplicar reglas entre capas.
- Exponer IPC genérico, procesos, secretos o filesystem a renderer.
- Añadir polling excesivo, bloqueos, estado global oculto o tareas ilimitadas.
- Borrar módulos funcionales o datos de usuario sin verificar dependencias y compatibilidad.
- Cometer credenciales, sesiones locales, builds o artefactos generados.

La descripción de la arquitectura y límites actuales se conserva en `docs/architecture.md`; comprueba el código antes de asumir que un proveedor expone un dato.


## Electron: ventana sin marco e Inicio

- La ventana principal Electron usa `frame: false`, conserva `resizable`, tamano minimo, sombra y comportamiento de cierre/taskbar. El renderer tiene `contextIsolation`, `sandbox` y `nodeIntegration: false`; no habilitar APIs Node.
- El proceso principal define `MIN_WINDOW_WIDTH` y `MIN_WINDOW_HEIGHT` como tamaño inicial y mínimo nativo de `BrowserWindow`; consulta el `workArea` DIP del monitor primario para centrar la ventana y reducir ambos límites solo si el área útil no alcanza. No se maximiza al iniciar ni se corrigen tamaños desde CSS.
- La cabecera React usa regiones nativas `-webkit-app-region: drag` para mover la ventana sin marco. Las pestañas y controles son `no-drag` para conservar los clics; los espacios libres de la barra y entre pestañas permiten arrastrar. El doble clic en el espacio vacío alterna maximizar/restaurar. Minimize, close, toggleMaximize, getWindowState y onWindowState son la API de ventana expuesta por preload; todos los IPC se verifican en main contra el renderer de confianza.
- El Home React vive en `frontend/src/pages/HomeDashboard.tsx`. Sus tipos de datos se declaran en `frontend/src/types/contracts.ts`; las operaciones allowlisted se agregan coordinadamente en main, preload y `backend/application.py`.
- Inicio muestra la tarjeta principal de estad?sticas SoloQ con sparklines para las m?tricas hist?ricas disponibles; debajo fluyen actividad, colecci?n, counter, Win Rate, matchups y aliados en la columna principal independiente. La columna derecha conserva rango, historial reciente, campeones, preferencias y rendimiento reciente. El historial tiene alto acotado y scroll interno. El selector de posici?n usa agregados y serie hist?rica ya entregados por Python.
- El Home consume `home.dashboard`, `home.sync`, `home.matches` y `home.clear-history`. Python reutiliza `HomeHistoryRepository`, `LCUHomeProvider` y `analyze_home_history`; la sincronizacion LCU se ejecuta fuera del lector JSONL en un pool acotado. La interfaz nunca agrupa companeros anonimizados por nombre: el servicio heredado solo presenta identidades verificables. No devolver PUUID, accountId, credenciales, roster completo ni payloads LCU al renderer.
- El Home primero muestra el estado en cache, sincroniza LCU al conectar y permite sincronizacion manual. Un reinicio del backend conserva el dashboard y vuelve a consultar el cache al reconectar; no ejecuta bucles de reintento ni reinicia automaticamente Python.
- `analytics.recent_performance` compara los 10 partidos SoloQ completados mas recientes con los diez anteriores (cola 420), deduplicados por ID y ordenados por timestamp. Python calcula KDA agregado como (kills + asistencias) / muertes, CS/min como CS total / minutos validos y vision como media solo de partidas con `vision_score`. Cero muertes produce KDA no finito y no se fuerza a cero. Las comparaciones y tendencias usan solo metricas presentes en ambos periodos; umbrales de 0,25 KDA, 0,3 CS/min y 2 puntos de vision moderan ruido. Con menos de 20 partidas, no hay comparacion completa.
- `analytics.champion_performance` agrupa partidas SoloQ por `champion_id` numerico canonico, calcula victorias/WR y KDA agregado, y prioriza campeones con al menos cinco partidas antes de completar hasta tres con muestras menores claramente marcadas. `home.assets` resuelve esos IDs via Data Dragon `key` a ID canonico y reutiliza la cache; las dos tarjetas se integran en el mismo `home.dashboard` sin peticion analitica adicional.
- `analytics.ranked_dashboard` se calcula en Python con partidas únicas de cola 420: métricas filtrables por posición (ALL incluye solo SoloQ), conteo de roles, top campeones y arquetipo. Tags Data Dragon multi-clase se ponderan equitativamente. Daño/min, participación y CS/min usan estadísticas de participante y duración válidas; la participación suma las muertes del equipo rival (equivalentes a las bajas del equipo local), no las muertes aliadas. Los registros históricos sin `is_local` pueden resolver al jugador únicamente por campeón y KDA coincidentes; los casos ambiguos permanecen sin atribución. `home.sync` conserva el `platformId` de `/lol-chat/v1/me` para enrutar Riot Match-V5. BattleScore solo se presenta cuando la puntuación final versionada v4 ya está persistida; el Home no inventa ni recalcula otra escala. Oro al 15 requiere una medición exacta de timeline persistida. El counter recorre todo el historial local y cuenta cada campeón rival una sola vez por derrota; actividad asigna cada partida una vez por su hora local de inicio. Los LP por partida, el total del catálogo de skins y las imágenes de skins no se fabrican si no están guardados/servidos por una fuente local.
- `performance_evolution_by_role` conserva en el contrato las ?ltimas 30 partidas SoloQ ?nicas en orden cronol?gico para ALL y cada posici?n; los datos incluyen KDA, CS/min, da?o/min, participaci?n, bajas en solitario, oro al 15 y BattleScore solo cuando existe un resultado final validado. La tarjeta principal dibuja sparklines sin ejes junto a sus promedios y el selector de posici?n elige una serie ya calculada, sin solicitudes adicionales.
- `home.assets` acepta hasta 20 identificadores de campeón para iconos y hasta tres para splash. Resuelve nombres/alias vía el catálogo Data Dragon; los splash se leen solo de `data/champion_splashes/` ya cacheados, no se envían rutas y no se descargan al cambiar el filtro. Limitar splash a los campeones visibles evita transportar múltiples fondos de varios megabytes por RPC.
- Para validar el Home: `.\.venv\Scripts\python.exe -m pytest tests -q` y `npm --prefix frontend run build`. La suite frontend no tiene runner separado configurado. La ventana Electron real, DPI y multi-monitor requieren validacion Windows interactiva.

## Frontend visual: codificacion, iconos y recursos

- Mantener los fuentes de React, TypeScript, HTML, CSS y contratos en UTF-8. `frontend/index.html` declara `meta charset=UTF-8`; no reparar texto en runtime ni decodificar JSON por segunda vez. Los mensajes JSONL de Python usan `ensure_ascii=False` y Electron opera en UTF-8.
- Usar `--font-sans` y los tokens CSS compartidos para la tipografia; no declarar familias no empaquetadas como Manrope o DM Sans sin fallback sans-serif. Los iconos de interfaz se dibujan como SVG con `frontend/src/components/Icon.tsx`; los botones solo icono necesitan `aria-label`.
- Los scrollbars se estilizan globalmente en `frontend/src/styles.css`. El shell ocupa el viewport; rail y topbar permanecen fijos y `.content` es la region principal desplazable. No ocultar scrollbars desactivando el scroll ni introducir desplazamiento anidado sin necesidad.
- `frontend/src/components/GameImage.tsx` centraliza imagen y fallback. El renderer no conoce rutas locales ni obtiene recursos Data Dragon. La operacion limitada `home.assets` entrega data URLs PNG para nombres resueltos contra el catalogo canonico y un `profileIconId`; validar y mantener su allowlist en main, preload y backend.
- Los iconos se resuelven en Python mediante la version de `data/champion_catalog.json` (con respaldo en `data/items.json`), reutilizando `~/.solralol/ddragon/` y `data/champion_icons/`; la descarga solo escribe en la cache del usuario. No aceptar rutas desde el renderer ni duplicar la logica de adquisicion.
- Usar `--type-micro`, `--type-meta`, `--type-secondary` y `--type-body` para la metadata del Home, con truncado o reflujo en columnas estrechas antes de reducir el tamaño tipografico. Mantener títulos y cifras principales existentes; los separadores de métricas se expresan como texto semántico legible (por ejemplo, `·`), no como `?` ni glifos decorativos inciertos.

## Sidebar React

- El sidebar vive en `frontend/src/pages/App.tsx` y comparte una sola lista de destinos para ambos anchos. Su preferencia expandida/colapsada se inicializa y persiste en `localStorage` con la clave `solralol.sidebarCollapsed`; no requiere peticiones al backend.
- El boton de alternancia va en el pie, inmediatamente antes del estado de conexion; expandido ocupa el ancho de los controles y muestra etiqueta, compacto queda como boton iconico centrado. En modo compacto, los iconos de navegacion conservan sus `aria-label` y `title`, y el estado del backend queda disponible como punto con tooltip. No añadir pie de versión redundante.
- El layout Flexbox anima el ancho del rail y el basis del contenido con 260 ms (`cubic-bezier(.4,0,.2,1)`). En modo compacto, navegación, alternancia y estado usan controles cuadrados de 36 px y un eje centrado. El scroll de navegación reserva gutter por ambos lados. Respetar `prefers-reduced-motion`; no duplicar JSX ni añadir offsets por pantalla.

- `analytics.rolling_winrate` para Inicio se calcula en `calculate_soloq_rolling_winrate`: solo cola 420 (SoloQ), partidas locales unicas con identificador, resultado y fecha valida; selecciona las 30 mas recientes y las presenta en orden cronologico. La ventana movil es de diez y las primeras muestras parciales indican su tamano. `WinRateEvolution` puede derivar la misma serie desde la pagina de partidas ya cargada si el proceso Python activo aun no incluye el campo nuevo; no hace otra solicitud, ni estima LP, ni combina Flex, ARAM o Normal.

## Home: dashboard compacto y anal?ticas

- `HomeDashboard` mantiene dos flujos independientes: la columna principal muestra la tarjeta de perfil/estadisticas y, justo debajo, seis tarjetas en una cuadricula de dos columnas y tres filas (actividad/coleccion, counter/Win Rate, matchups/aliados); la barra derecha conserva rango, historial, campeones, preferencias y rendimiento reciente. Las filas de la cuadricula no esperan a que termine la barra derecha.
- El historial usa una tarjeta de alto acotado con cabecera/filtros, lista `minmax(0, 1fr)` de scroll interno y pie fijo. El lote visible solo altera filas; `home.matches` pagina y `home.match.detail` carga los equipos al abrir una partida. Los detalles serializados omiten PUUID, nombres de cuenta y otros identificadores privados.
- `analytics.ranked_dashboard` calcula en Python m?tricas por rol, distribuci?n/arquetipo, campe?n principal, actividad por hora local de inicio y counter por derrota sobre el historial local. `home.assets` reutiliza iconos y splash ya cacheados; cambiar de rol no env?a solicitudes anal?ticas.
- `performance_evolution_by_role` conserva en el contrato las ?ltimas 30 partidas SoloQ ?nicas en orden cronol?gico para ALL y cada posici?n; los datos incluyen KDA, CS/min, da?o/min, participaci?n, bajas en solitario, oro al 15 y BattleScore solo cuando existe un resultado final validado. La tarjeta principal dibuja sparklines sin ejes junto a sus promedios y el selector de posici?n elige una serie ya calculada, sin solicitudes adicionales.
- Verificación del renderer Electron real: ejecutar `npm run dev:debug` y luego `npm run test:home-layout` desde `frontend/`. El test DevTools comprueba los bordes inferiores (tolerancia 2 px), overflow y movimiento del scroll, y que cargar 100 filas no altere el alto del panel/documento; recorre 1280×720, 1600×900, 1920×1080 y 2560×1440 con sidebar expandido y plegado. Requiere el puerto DevTools 9230 activo y suficientes partidas locales.
- Home ranked metric contract: `stats_by_role` aggregates only unique queue-420 matches for ALL or the selected role. Vision is the mean of valid participant `vision_score`; DMG/min is total champion damage divided by total valid minutes; KP is player kills+assists divided by the five opposing participants' deaths. Per-match series are the latest 30 chronological matches and carry the same metric values for sparklines. Trend indicators compare the latest valid point with the mean of preceding valid points in that window; backend returns delta, direction, sample, and precision. Gold Diff @15 accepts signed values and uses local minus a unique trusted same-role opponent at the Riot timeline frame nearest 900000ms (within 30s); it maps PUUIDs first and legacy participant IDs second. `home.sync` incrementally backfills one match's missing Riot detail and/or eligible timeline per sync when an API key exists; Riot timelines are cached (bounded to 50), and local records store resolver version/result/attempt status. Missing information stays unavailable rather than being estimated.

## Electron settings

- `frontend/src/pages/SettingsPage.tsx` consumes `settings.load`, `settings.update`, `settings.key.save`, `settings.key.clear`, `settings.audio-devices` and `settings.recording-test`; keep method validation aligned in backend dispatch, Electron main allowlist, preload allowlist and TypeScript contracts.
- Settings updates are validated patches merged into the existing `~/.solralol/settings.json`; never send whole snapshots back or expose `riot_api_key` / `gemini_api_key` values to React. Failed credential validation keeps an existing saved key intact.
- Native directory selection, opening only the saved recordings directory and the two known provider URLs are limited Electron main-process operations. Do not add generic path, shell or command APIs to the renderer bridge.
- Settings values for recording and overlays retain their shared file format. Recording RPC and floating overlay windows run through the Electron backend; distinguish unavailable devices and display modes from valid persisted preferences.

## Electron Meta

- `MetaPage` reuses Python `ServicioMeta` through `meta.bootstrap`, `meta.tier`, `meta.notes` and the bounded `meta.assets` operation. Keep LoLalytics parsing, ranking validation, six-hour filters/cache and official patch discovery in Python; region selection remains in `settings.json` as `meta_region`.
- The original Meta filters are five roles, World/EUW/NA/KR, fixed Emerald+, Solo/Duo, champion search and ranking sort. Tier ranking retains source positions and pins the actual #1 row in the default order; never infer a champion or metrics in React.
- Patch notes use structured schema 4 sections with canonical champion/item/ability IDs. React renders text nodes only (never source HTML); editorial images are limited to HTTPS Riot/League/Contentstack hosts and Data Dragon images resolve through the bounded Python cache API.
- Replacing `patch_notes.json` is atomic; only after a valid replacement is stored may obsolete `patch_*_hero` files in the Meta cache be removed. Preserve unrelated Data Dragon assets and settings. Refresh/failure should retain a valid stale note copy.
- Shared champion identity normalization lives in `app/services/identidad_campeon.py`: exact normalized Riot IDs, keys, canonical names and verified localized aliases resolve against the Data Dragon catalog without fuzzy matching. The LoLalytics parser tries image `alt`, visible card text and URL slug; unresolved rows retain source positions and return `complete=false` plus name/position diagnostics so a missing #1 is never silently promoted. Electron displays partial ranking state. Meta RPC distinguishes `meta_source_unavailable` from `meta_source_invalid`; keep retry behavior user-driven when fresh data is unavailable.


- `app/services/item_name_aliases.py` is the canonical item-alias source used by `CatalogoAnalisisLocal` and Electron Local Analysis.
- Electron RPC `champions.analysis` fixes `emerald_plus` and reuses `AnalisisLocalService` to return the curated profile, rune-page variants, recommendations, item catalog, and local icons. `champions.analysis.update`, `.status`, and `.cancel` manage background refresh for one or all champions. Keep recommendation logic in Python.

### Draft Electron
- El destino Draft se implementa en `frontend/src/pages/DraftPage.tsx`; permanece montado dentro de la shell para conservar el estado manual y mantener una sola supervisión LCU (3 s activa, 8 s en segundo plano, sin solicitudes solapadas). El renderer compara snapshots y solo actualiza la vista cuando cambia el contenido.
- `backend/draft.py` es el adaptador Electron del `DraftAnalyzerService`, `RepositorioCampeones` y `LCUService` existentes. No duplica las puntuaciones analíticas; conserva Esmeralda+ para preparación, cachea composición brevemente y resuelve iconos mediante Data Dragon local/caché.
- `draft.snapshot` añade `analysis.composition.teams` con estimaciones de daño y curvas de duración calculadas por separado para aliados y rivales. El daño solo usa perfiles completos o con tipo de daño conocido; las curvas nuevas omiten tramos sin observaciones y exponen sus tamaños de muestra. La UI representa ambas series como estimaciones históricas, nunca como una probabilidad directa del enfrentamiento.
- El contrato IPC `draft.snapshot` entrega picks, intenciones, posiciones confirmadas/probables, baneos, análisis y preparación. El modo manual conserva equipos y baneos editables al no existir selección activa. Las líneas rivales inferidas nunca se tratan como confirmadas para matchups.
- `draft.import` acepta solo tipo, campeón, rol, índice de página y rivales. Python regenera el payload desde el repositorio y delega importación a `LCUService`; se preservan las páginas/conjuntos no gestionados y solo se comunica éxito tras respuesta válida del cliente.
- La verificación automatizada está en `tests/test_electron_draft.py`; cubre snapshot manual/LCU simulado y lectura de la variante local. La importación contra un cliente League activo necesita validación manual con LCU disponible.

### Grabaciones Electron
- backend/recordings.py supervisa captura automatica y reutiliza la configuracion FFmpeg, captura DXGI, biblioteca, sidecars y validacion MP4 de app/services/recording_service.py; solo inicia automaticamente con una ventana visible de League y finaliza tras 12 s de ausencia. Si cambia el monitor, cierra el segmento antes de reiniciar.
- El adaptador usa subprocess.Popen; `recording_service.py` contiene configuración, helpers FFmpeg, marcadores y biblioteca, sin un controlador de procesos de UI.
- recordings.list/status/start/stop/delete son RPC Electron; `recordings.source` comprueba acceso mediante un token temporal. El borrado queda confinado a nombres MP4/MKV bajo la biblioteca. El renderer no recibe rutas; solralol-recording:// sirve el vídeo en streaming. La CSP de `frontend/index.html` debe permitir explícitamente `media-src solralol-recording:` y mantener las demás directivas restrictivas. El protocolo admite GET/HEAD y rangos HTTP; el indicador de archivo finalizado no equivale a compatibilidad de reproducción.
- La captura usa DXGI Desktop Duplication del monitor completo. FFmpeg elige entre AMF/NVENC/QSV disponibles y libx264 como respaldo; GOP de 2 s y +faststart. Audio por proceso de League no esta disponible; microfono y mezcla del sistema respetan ajustes.
- UI: frontend/src/pages/RecordingsPage.tsx. Pruebas del contrato: `tests/test_electron_recordings.py`. La validacion real requiere League y hardware compatibles.

### BattleScore 2.7
- `backend/battlescore.py` delega en `backend/battlescore_engine.py`, motor autoritativo `battlescore_v2_7`; `backend/battlescore_v2_6.py` conserva v2.6 para comparaci?n y v2.5 tambi?n permanece disponible. Escala 0.10?10.00, inicio 5.00, sin decaimiento antes de 2:00; decaimiento ?0.14/min sobre 2 y ?0.085/min bajo 2. Oro +0.150/1.000, EXP +0.014/1.000 y muerte ?0.270 antes del multiplicador de rol. V2.7 ajusta ?nicamente: Top bajas/EXP 1.05/1.05; Jungla oro/estructura 0.85/0.85; Medio bajas 1.15; Apoyo oro/asistencias 0.70/1.20. Los dem?s multiplicadores se conservan.
- Oro y EXP usan deltas positivos de cronología; la primera observación es baseline. Los totales fiables sin marca temporal se asignan linealmente como estimación para evitar un salto terminal. Se identifican en `estimatedAllocations`; no son eventos Riot observados. El desglose conserva recompensa base, ajuste contextual y total por componente.
- La migración de puntuaciones antiguas ocurre al leer la lista de análisis guardados y reutiliza únicamente cronología/datos Match-V5 ya almacenados; no solicita datos nuevos a Riot. La calibración disponible cuenta con una partida guardada como análisis y 49 partidas locales utilizadas para las medianas, así que no equivale a validación global.

### Electron Live Match

- `backend/live_match.py` lazily starts one authoritative background LCU/gameflow and Live Client monitor when `live.snapshot` is first requested. It continues after navigation; reads from renderer return the bounded latest state. Lifecycle snapshots use 2 s cadence, Live Client telemetry reads `activeplayer`, `playerlist`, `gamestats`, and `eventdata` individually, and a three-failure grace retains snapshots/session before completion.
- Electron Live page: `frontend/src/pages/LiveMatchPage.tsx`. It distinguishes disconnected, connected, lobby, champion select, loading, active, game ending, stale telemetry and post-game, shows available player/team values and exact event timestamps, and resolves portraits/items through `home.assets`/`meta.assets`. `?liveFixture=active` in Vite shows clearly marked simulated data.
- Tracker persistence reuses `LiveMatchTracker` and its existing ten-session retention/deduplication. The only FFmpeg owner remains `backend/recordings.py`; it receives the current session ID for its sidecar. Current overlay behavior and API/display limitations are documented in `docs/live-match.md`.
- Six Electron overlay types consume the live snapshot, and Settings previews use the same React views with isolated data. Fixture tests cover state and contracts; they do not constitute real League, fullscreen, DPI, or hardware validation.
