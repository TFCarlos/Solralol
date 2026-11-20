# Solralol

Solralol es una aplicación de escritorio para **Windows** que acompaña a jugadores de League of Legends. Reúne historial local, estadísticas clasificatorias, análisis de campeones y partidas, preparación de selección, seguimiento en vivo y grabaciones para ayudar a revisar decisiones y mejorar el juego. Es un proyecto independiente de Riot Games y sigue en desarrollo activo.

## Funciones principales

| Sección | Función disponible y límites |
| --- | --- |
| **Inicio** | Perfil e historial sincronizados con el cliente, métricas por posición, actividad, campeones frecuentes, enfrentamientos, aliados identificables y evolución del porcentaje de victorias. Los agregados clasificatorios usan partidas únicas de **Solo/Dúo, cola 420**; las muestras incompletas se indican. |
| **Análisis local** | Perfiles por campeón y posición con variantes de runas, builds, hechizos, orden de habilidades, enfrentamientos y recomendaciones de objetos. La preparación usa datos locales y estadísticas externas cuando están disponibles; el rango de preparación es Esmeralda+. Puede actualizarse por campeón o en lote. |
| **Draft** | Selección manual y seguimiento de selección de campeones mediante LCU. Muestra composiciones, baneos y preparación; puede importar páginas de runas y conjuntos de objetos al cliente cuando la conexión lo permite. Las estimaciones históricas no son probabilidades directas de ganar. |
| **Partida en vivo** | Estado de partida, jugadores, inventarios, eventos con hora observada, recomendaciones de compra y preparación. Usa Live Client Data API y LCU; muestra estados parciales o no disponibles. El contador de regreso enemigo se basa en cambios de inventario o reapariciones observadas: **no confirma un Recall**. |
| **Partidas guardadas** | Biblioteca y detalle de partidas, revisión de eventos, indicadores positivos y oportunidades de mejora. El análisis profundo con Match-V5, cronología y **BattleScore v2.7** se activa para partidas Solo/Dúo de cola 420 con datos verificables; existe un límite configurable de análisis activos. Inicio reutiliza BattleScore solo cuando hay un resultado final guardado. |
| **Análisis con IA** | Generación bajo petición para partidas analizables, asociada a la partida y guardada localmente. Requiere una clave de Gemini; su contenido depende de la telemetría disponible. |
| **Grabaciones** | Captura automática o manual, biblioteca, reproducción y revisión con marcadores cuando existen datos asociados. La captura usa FFmpeg y DXGI sobre el monitor. La reproducción depende de que el archivo final sea válido y compatible. El audio aislado por proceso de League no está disponible. |
| **Meta y notas** | Clasificaciones por posición y región procedentes de LoLalytics, con estado parcial cuando faltan filas; notas de parche de fuentes oficiales y recursos Data Dragon. La disponibilidad depende de las fuentes y la red. |
| **Ajustes** | Credenciales Riot/Gemini, grabación, audio, overlays, análisis y ubicación de datos. Las claves se conservan en el backend y la interfaz solo recibe indicadores de configuración. El traslado de almacenamiento conserva el origen y valida la copia antes de cambiar la ubicación activa. |

Hay **cinco paneles flotantes** configurables: diferencia de oro, alertas, compra recomendada, último regreso enemigo estimado y orden de habilidades. Se pueden previsualizar y colocar desde Ajustes. Su visibilidad depende del modo de pantalla y de otras ventanas; la pantalla completa exclusiva puede impedir mostrar ventanas externas. Los avisos de objetivos e inhibidores requieren eventos e identificadores suficientes y no afirman reapariciones no confirmadas.

## Arquitectura y tecnologías

La aplicación de producto usa **Electron, React 19, TypeScript y Vite**. Electron crea la ventana principal y los overlays, supervisa un único proceso Python y restringe las operaciones IPC. El preload expone `window.solralol` mediante `contextBridge`; el renderer funciona con aislamiento de contexto, sandbox y Node deshabilitado.

El backend **Python** recibe solicitudes JSON Lines por `stdin` y devuelve exclusivamente respuestas de protocolo por `stdout`; los diagnósticos van a `stderr`. No abre un servidor local ni usa Qt. Python gestiona LCU/Live Client, Riot Match-V5, normalización, analítica, recomendaciones, persistencia y grabación. El contrato compartido está tipado en TypeScript y validado en Python.

Las fuentes incluyen los catálogos y recursos **Riot Data Dragon**, el cliente local de League, **Riot Match-V5** cuando hay clave válida, LoLalytics para Meta, fuentes estadísticas de análisis de campeones y **Gemini** para análisis opcional. La captura emplea FFmpeg, localizado por configuración, sistema o `imageio-ffmpeg`. Los proveedores externos pueden cambiar o no estar disponibles.

| Ruta | Responsabilidad |
| --- | --- |
| `frontend/src/` | Pantallas React, componentes, overlays y contratos del renderer. |
| `frontend/electron/main/` y `frontend/electron/preload/` | Ventanas, proceso Python, IPC limitado y protocolos de recursos. |
| `backend/` | Protocolo JSONL, fachada de operaciones y adaptadores de funciones. |
| `app/services/` | Servicios de dominio, repositorios e integraciones compartidas. |
| `data/` | Catálogos y recursos incluidos con la aplicación. |
| `tests/`, `frontend/scripts/`, `docs/` | Pruebas, verificaciones del renderer y documentación técnica. |

`solralol_dev.py` es un panel **opcional de desarrollo** basado en PySide6. No es la interfaz del producto.

## Requisitos e instalación para desarrollo

- **Windows** para la aplicación y sus integraciones nativas de captura y ventanas.
- **Python 3.11** disponible mediante `py -3.11`, según el procedimiento de desarrollo del proyecto.
- **Node.js 22.12 o superior** y npm (requisito del Electron incluido en el lockfile).
- Cliente de League of Legends para LCU, Draft y datos en vivo. Las pruebas de escritorio pueden ejecutarse sin una partida activa.
- Acceso a Internet para instalar dependencias y actualizar datos externos.

Desde PowerShell, en la raíz del repositorio:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend ci
npm run dev
```

`npm run dev` inicia Vite y Electron; Electron arranca y cierra el backend Python privado. `SOLRALOL_PYTHON` permite elegir otro intérprete si no se usa `.venv\Scripts\python.exe`. `npm run dev:debug` habilita los puertos de depuración locales definidos por el proyecto. La herramienta opcional `solralol_dev.py`, la depuración Python y el empaquetado requieren:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

No hace falta crear un archivo de entorno para arrancar. Configura las claves **desde Ajustes**: Riot para descargas Match-V5 y Gemini solo si deseas análisis con IA. La conexión LCU se detecta desde el cliente local en ejecución; no copies el `lockfile` ni claves al repositorio. Para Live Match, inicia una partida compatible y mantén el cliente y el juego abiertos.

## Compilación y empaquetado

```powershell
npm run build
npm run dist:win
```

El primer comando ejecuta TypeScript y Vite. El segundo construye el backend con PyInstaller y genera un instalador Windows NSIS mediante electron-builder en `frontend/release/`; requiere `requirements-dev.txt` y las dependencias npm instaladas. Los artefactos de build no se publican como código fuente. El funcionamiento del instalador y de las integraciones con el juego requiere verificación en una instalación limpia.

## Uso y datos locales

Abre **Inicio** para consultar el historial en caché y sincronizar con LCU cuando el cliente esté conectado. Desde una partida Solo/Dúo de cola 420 puedes activar el análisis profundo; **Partidas guardadas** permite revisar detalles, cronología, BattleScore y análisis con IA cuando existan datos y credenciales suficientes. Usa **Análisis local** para preparar un campeón, **Draft** durante la selección y **Partida en vivo** durante el juego. En **Grabaciones** puedes revisar clips finalizados y en **Ajustes** controlar captura, overlays y almacenamiento.

Los ajustes, sesiones, historial, análisis y vídeos se guardan en la carpeta de datos activa (por defecto `%USERPROFILE%\.solralol`). `%APPDATA%\Solralol\storage.json` apunta a esa ubicación si se cambia. `data/` contiene recursos del proyecto; no es la biblioteca personal. No subas la carpeta de usuario, claves, partidas privadas ni grabaciones a GitHub.

## Estado del desarrollo y tareas pendientes

**Solralol sigue en desarrollo activo.** Esta lista separa fallos reproducidos de comprobaciones que aún requieren League, hardware o datos reales. Las pruebas con fixtures no acreditan compatibilidad con una partida real.

### Bugs pendientes de solucionar

- [x] Corregida la pérdida de `position` al normalizar participantes LCU; las pruebas de resolución del rival de línea vuelven a pasar. Las otras expectativas que fallaban se ajustaron a los contratos actuales de métricas, BattleScore y logros.
- [x] El banco de pruebas cierra los monitores de grabación que crea; antes pytest terminaba las aserciones pero quedaba esperando hilos de tests.
- [ ] Comprobar con LCU real que la posición y el rival de línea se resuelven correctamente en los formatos que entrega el cliente actual. **No hay un defecto adicional confirmado** por esta comprobación pendiente.

### Funcionalidades pendientes de completar

- [ ] Obtener una fuente fiable de eventos de **Recall** antes de presentar contadores enemigos como regresos confirmados; el estado actual solo ofrece observaciones e inferencias identificadas.
- [ ] Las categorías de mejora deshabilitadas por falta de atribución individual fiable, como `unattended_objectives`, deben seguir deshabilitadas hasta contar con datos verificables. `forgotten_dragons` solo evalúa cronología suficiente; no convierte la ausencia de datos en un hallazgo.
- [ ] Evaluar la consistencia del análisis con IA y ampliar la calibración independiente de BattleScore v2.7 antes de interpretar las puntuaciones como una medida general validada. La calibración local disponible es limitada.
- [ ] Definir una política explícita para identificar y retirar datos heredados realmente obsoletos tras una migración; conservar siempre historial, ajustes, análisis y grabaciones sin borrado implícito.

### Mejoras de rendimiento y optimización

- [ ] Dividir la carga del renderer: el build actual avisa de un bloque JavaScript de **610,58 kB** minificado, mayor que el umbral de 500 kB.
- [ ] Medir tiempos de inicio, cambios de sección, volumen de actualizaciones del renderer, consumo en segundo plano y búsqueda/salto en vídeos largos con bibliotecas reales; no hay medición de release en este equipo.
- [ ] Medir el coste de captura durante una partida real antes de afirmar impacto aceptable en FPS, CPU, GPU o disco.

### Mejoras visuales y de experiencia de usuario

- [ ] Revisar en Windows real escalado DPI, varios monitores, tamaños mínimos, navegación y disposición de paneles flotantes. Las vistas con datos parciales y los mensajes de proveedor externo requieren revisión de legibilidad.
- [ ] Ajustar el anclaje del indicador de habilidad al HUD real; la API Live Client no proporciona coordenadas exactas del HUD.

### Pruebas y validaciones pendientes

- [x] Pasar la suite Python, las pruebas Node de cierre/BattleScore y los checks con fixtures de Electron/Chromium para timeline, preparación y overlays.
- [ ] Ejecutar `test:home-layout` con Electron de desarrollo, puerto DevTools 9230 y suficientes partidas locales; verificar el diseño con los datos del usuario sin modificar su biblioteca.
- [ ] Probar inicio/cierre con cliente League y grabación activos, pérdida y recuperación de LCU/Live Client, importación real de runas/builds para Aurelion Sol y Wukong, y actualización de recomendaciones tras compras. La normalización de ambos campeones y la importación simulada tienen pruebas, pero no sustituyen LCU real.
- [ ] Probar eventos atribuidos a campeones, torres y súbditos, temporizadores de objetivos/inhibidores, alertas, sonido y órdenes de habilidades en partidas reales y diferentes parches. Hay cobertura automatizada de normalización, temporizadores y estados; falta comprobar la fuente en juego.
- [ ] Probar overlays al alternar juego/otras ventanas, parpadeos, tiempos de notificación, clic transparente y limpieza al salir, en ventana, sin bordes, varios monitores y pantalla completa exclusiva. La lógica de oclusión tiene pruebas de fixtures; el modo exclusivo puede bloquear ventanas externas.
- [ ] Verificar en partidas guardadas de distintos parches iconos de objetos, runas y hechizos, cronología, disponibilidad de BattleScore y reutilización de puntuaciones en Inicio. Hay pruebas de resolución con caché simulada; faltan fuentes reales y archivos antiguos.
- [ ] Probar grabación, audio, reproducción, salto y borrado con FFmpeg/hardware reales, además del límite de almacenamiento y recuperación de `.lock` heredados. Las rutas de recuperación están cubiertas por pruebas temporales, no por una biblioteca de usuario real.
- [ ] Validar el instalador Windows en una máquina limpia y una migración de almacenamiento real entre unidades; las pruebas automatizadas de migración usan datos temporales y conservan el origen.
- [ ] Revisar manualmente la historia anterior de Git antes de una publicación pública: contiene material histórico de pruebas y referencias locales. Excluirlo del árbol actual no elimina los commits anteriores.

## Desarrollo y pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
node --test tests/electron_shutdown_coordinator.test.cjs tests/frontend/battleScoreTimeline.test.mjs
npm --prefix frontend run build
```

La suite frontend no tiene un runner único. Los scripts visuales de `frontend/package.json` usan Chromium/Electron de desarrollo y requisitos propios; consulta `docs/` para sus límites. Los comandos de arriba verifican lógica y compilación, pero no sustituyen las validaciones con League, LCU, audio, DXGI o fullscreen.
