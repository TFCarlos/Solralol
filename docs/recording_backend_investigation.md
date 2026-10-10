# Investigación del backend de grabación

Fecha: 2026-10-10

## Hallazgos de la implementación

- `RecordingService.start` construye argumentos FFmpeg y lo lanza con `QProcess`.
- El modo juego usa FFmpeg `gdigrab` con `title=<título>`; el modo explícito `all` usa `gdigrab` sobre `desktop`. El título se obtiene de un HWND visible cuyo PID resuelve a `League of Legends.exe`. No hay validación de frames antes de dar el inicio por correcto.
- La captura no llama APIs para activar, restaurar, minimizar o mover la ventana. `QProcess.start()` por sí solo no cambia el foco. Las llamadas `raise_()`/`activateWindow()` localizadas en `main_window.py` pertenecen a las ventanas de repaso, no al arranque del grabador.
- El vídeo se escala en CPU y se codifica con `libx264`, `veryfast`, hasta ocho hilos. El proceso une stdout y stderr; la salida se consulta al fallar, no se analiza de forma continua. Durante una captura correcta no recoge estadísticas de FPS, cuadros descartados, uso GPU/CPU ni caudal de disco.
- El audio de micrófono y modo sistema entra por DirectShow y se mezcla con `amix`. No había una fuente de audio por proceso para «Solo juego». El estado previo aceptaba MP4 de cualquier tamaño mayor que cero y no inspeccionaba streams, timestamps ni imagen.
- La grabación automática se inicia cuando la integración LIVE detecta la partida. Si el ejecutable o la ventana aún no está disponible en ese instante, el inicio actual falla; no hay espera acotada/worker de preparación.
- En el equipo de desarrollo no hay OBS instalado ni `League of Legends.exe` activo. El cliente Riot está abierto, pero no es el proceso de juego. El FFmpeg incluido declara `gdigrab`, `libx264`, AAC y los encoders `h264_nvenc`, `h264_amf` y `h264_qsv`; listar un encoder no demuestra que su dispositivo o controlador puedan inicializarlo.

## Comparación de arquitecturas

| Opción | Ventajas | Costes y riesgos |
| --- | --- | --- |
| Integrar libobs directamente | Fuentes de captura, mezcla, sincronización y encoders maduros; control directo sin ventana de OBS | Debe distribuir y mantener libobs, Qt/OBS y módulos compatibles; ABI y plugins nativos; el puente Python no elimina el trabajo con hilos, gráficos y ciclo de vida nativo. Mucho riesgo de empaquetado para esta app PyInstaller. |
| OBS aislado y controlado por obs-websocket | Reutiliza el motor y fuentes oficiales; API versionada para entradas, salidas, escenas y estado; se puede aislar con perfil/colección Solralol sin tocar escenas existentes. Permite delegar captura y sincronización a OBS. | Dependencia externa de OBS; otro proceso y uso adicional de memoria; debe arrancarse oculto sin tomar foco, aprovisionar solo su perfil aislado y validar versión/plugins/encoder. La gestión de grabación debe distinguir instancia propia de OBS preexistente. |
| Captura propia WGC + encoder HW + AudioClient process loopback | Integración compacta y sin motor OBS; cero hooks al proceso del juego si se usa WGC; buen control de buffers y latencia | Requiere implementar/soportar interoperabilidad WinRT/D3D, superficie y encoder, `ActivateAudioInterfaceAsync`, callbacks/audio client, sincronización, recuperación y packaging por GPU/Windows. Coste y matriz de compatibilidad mayores que la capacidad actual de mantenimiento Python/Qt. |

## Decisión propuesta

Usar **OBS gestionado por Solralol**, con dependencia detectada y motor dedicado. La fuente de vídeo preferida será `Window Capture` con Windows Graphics Capture y prioridad de coincidencia por ejecutable, resolviendo primero la ventana de `League of Legends.exe`. No usar `Game Capture`/inyección de hooks por defecto: OBS documenta para League el uso de captura de ventana y recomienda alternativa de ventana para ciertos conflictos de anti-cheat. La fuente de ventana puede incluir su audio en OBS 30.1+ en Windows 10 2004/Windows 11; exigir esa capacidad para «Solo juego» y validar que el dispositivo entregue audio.

La instancia debe usar perfil y colección propios, loopback websocket limitado a localhost con contraseña aleatoria de vida de proceso, codificador HW validado antes de comenzar y ventana principal oculta desde `CreateProcess` (sin enviar teclas ni activar ventanas). Si no puede inicializar una captura de ventana WGC fresca o audio de aplicación cuando ese modo está solicitado, no debe empezar la grabación. No usar escritorio como respaldo.

El modo software solo se ofrecerá como elección explícita. NVENC/AMF/QSV deben seleccionarse después de una prueba corta de inicialización; no basta la salida de `ffmpeg -encoders`. OBS se recomienda para remux/MP4 después de grabar MKV, de forma que una parada forzada no deje el contenedor MP4 irrecuperable.

## Validación todavía necesaria

La decisión no equivale a validar OBS contra esta instalación de League/Vanguard. Hace falta OBS 30.1+, Windows 10 2004 o Windows 11, y una partida real para comprobar WGC, audio de proceso, alt-tab, resolución, minimización, encoder, foco, rendimiento y streams finales. No se midieron benchmarks porque el juego no está activo y OBS no está instalado aquí.
