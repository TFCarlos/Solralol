# SOLRALOL

<p align="center">
  <img src="data/LogoApp.png" alt="Logotipo de SOLRALOL" width="96">
</p>

**SOLRALOL es una aplicación de escritorio para Windows que acompaña partidas de League of Legends.** Está desarrollada en Python y PySide6. Reúne análisis de campeones y draft, datos en directo, historial, revisión de partidas y grabaciones locales.

La interfaz está en español. SOLRALOL es un proyecto independiente; no está afiliado ni respaldado por Riot Games.

## Funciones

### Inicio e historial

Consulta el perfil y el historial disponibles en el cliente local de League (LCU). SOLRALOL conserva un historial propio por cuenta y puede enlazar partidas guardadas, mostrar estadísticas y recuperar datos de colección cuando el cliente los ofrece. Los datos guardados localmente pueden seguir consultándose con League cerrado.

### Análisis de campeones

Consulta perfiles y estadísticas locales por campeón, línea y rango: Esmeralda, Esmeralda+, Diamante, Diamante+, Master y Master+. Esmeralda+ es el filtro inicial. El análisis puede incluir enfrentamientos, páginas de runas, hechizos, orden de habilidades, objetos iniciales, núcleo, build completa y recomendaciones situacionales.

Las páginas de runas disponibles pueden definir perfiles de build distintos. Al seleccionar otra página, el análisis usa el perfil de build asociado si está disponible. La selección no inventa estadísticas: las tasas y muestras mostradas proceden de los datos guardados o de la fuente identificada.

Las actualizaciones de datos son explícitas y se ejecutan en segundo plano. Se consultan U.GG, OP.GG, Lolalytics y Data Dragon según la operación. La disponibilidad y el formato de esos servicios pueden cambiar.

### Herramienta de Draft

Planifica composiciones manualmente o consulta la selección de campeón activa del cliente. Muestra comparativas y recomendaciones de campeones, runas, objetos y hechizos. La importación de una preparación y la lectura de picks o bans requieren que el cliente de League esté disponible mediante LCU.

### Partida en vivo y overlay

Durante una partida, la aplicación consulta la Live Client Data API local para mostrar los datos que publica el juego. Puede guardar eventos y telemetría local, ofrecer recomendaciones y mostrar un overlay opcional con alertas. Los campos disponibles dependen del modo y de la respuesta del juego.

### Partidas guardadas y revisión

Las sesiones pueden conservar eventos, instantáneas, cronologías y datos finales disponibles. La ventana de revisión relaciona los eventos guardados con una grabación cuando existe. La sincronización posterior con Riot y los análisis con Gemini son funciones opcionales.

### Grabaciones

La biblioteca administra archivos de vídeo y sus metadatos locales, permite reproducirlos y saltar a marcadores relacionados con eventos. La grabación usa FFmpeg y el filtro `ddagrab` de Desktop Duplication (DXGI) para capturar un monitor. Al iniciar, se elige el monitor que contiene la ventana visible de League; si no se detecta el juego, se usa el monitor configurado. El monitor elegido permanece fijo durante esa sesión.

La salida usa H.264 mediante el codificador `h264_amf` y los ajustes configurados de resolución, FPS y bitrate. La disponibilidad depende de que FFmpeg incluya ese filtro y codificador y de que el equipo pueda inicializar AMF. La aplicación no debe interpretarse como compatible con todos los fabricantes de GPU por el mero hecho de que tengan codificación por hardware.

El audio se configura por separado. **Solo juego** requiere una fuente de entrada de audio disponible que pueda capturar la salida del juego; el backend actual no implementa loopback por proceso de Windows. Si no hay una fuente compatible, la grabación puede quedar sin audio de juego. No se requiere micrófono para grabar vídeo, y el modo de audio del sistema puede incluir sonido de otras aplicaciones según el dispositivo elegido.

La grabación puede iniciarse manualmente desde **Grabaciones** o automáticamente según la configuración y los eventos de partida. No se debe considerar validada una captura solo porque se haya creado un archivo: revisa el estado y reproduce el resultado para confirmar imagen y sonido en tu equipo.

### Ajustes

Configura claves y Riot ID, preferencias de grabación, carpeta y límite de almacenamiento, dispositivos de audio, overlay y alertas. Las claves se guardan en el archivo local de ajustes como valores JSON sin cifrado; protege ese archivo y no lo compartas con secretos incluidos.

## Requisitos

- Windows, la plataforma objetivo del proyecto.
- Python 3.11 o posterior.
- Dependencias de `requirements.txt`.
- FFmpeg utilizable para las funciones de grabación. `imageio-ffmpeg` proporciona un binario cuando está disponible; también se puede configurar o detectar una instalación compatible.
- Cliente de League instalado para las funciones que usan LCU o datos de partida. El cliente no es necesario para abrir la aplicación y consultar datos locales ya guardados.
- Conexión a Internet para actualizar catálogos y datos externos.

Algunas funciones requieren configuración adicional: una clave de Riot para operaciones compatibles con Riot Games API y una clave de Google AI Studio para solicitar análisis de Gemini. Ninguna de ellas es necesaria para las funciones locales básicas.

## Instalación y ejecución

Desde PowerShell, en la raíz del repositorio:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

También se puede iniciar con `run.bat` después de crear `.venv` e instalar las dependencias. La aplicación intenta actualizar el catálogo de objetos Data Dragon al arrancar y usa la copia local si la actualización falla.

## Datos y privacidad

La configuración se guarda en `~/.solralol/settings.json` (en Windows, dentro del perfil del usuario). Los datos locales pueden incluir historial, sesiones, grabaciones, metadatos, preferencias y claves configuradas. Las credenciales de LCU se obtienen del lockfile local del cliente; no hace falta copiarlas a los ajustes.

Las solicitudes a LCU y a Live Client permanecen en el equipo. Las funciones de actualización consultan Data Dragon y proveedores públicos de estadísticas. La sincronización solicitada envía peticiones a Riot Games API. Cuando se solicita un análisis de Gemini, el contenido de análisis correspondiente se envía a Google AI Studio. El usuario controla cuándo ejecutar estas funciones externas.

Los endpoints LCU y Live Client son interfaces locales del juego y pueden cambiar. Los datos de estadísticas dependen de la cobertura, parche y muestra de cada proveedor; la aplicación puede mostrar información parcial o no disponible.

## Arquitectura del repositorio

```text
SOLRALOL/
|-- main.py                 # Entrada de la aplicación
|-- _paths.py               # Rutas de desarrollo y empaquetado
|-- data_dragon.py          # Catálogos y recursos de Data Dragon
|-- requirements.txt        # Dependencias de Python
|-- run.bat                 # Lanzador de Windows
|-- main.spec               # Configuración de PyInstaller
|-- app/
|   |-- ui/                 # Ventanas, páginas, widgets y workers de Qt
|   |-- services/           # Lógica, datos, integraciones y grabación
|   |-- models/             # Modelos compartidos
|   |-- utils/              # Utilidades
|   `-- scratch/            # Pruebas y recursos de validación
`-- data/
    |-- champion_data/      # Datos locales por campeón y variante
    |-- champion_metadata/  # Metadatos estáticos de campeones
    |-- champion_abilities/ # Datos de habilidades
    `-- ...                 # Catálogos e iconos locales
```

La interfaz delega adquisición de datos y cálculos a `app/services/`. Las tareas bloqueantes usan workers o mecanismos asíncronos para no detener el hilo de Qt. El análisis habitual lee el repositorio local; las consultas a proveedores se inician mediante acciones de actualización o funciones que las requieren.

## Pruebas y comprobaciones

Las pruebas y fixtures sin servicios externos se guardan en `app/scratch/`. `pytest` y `ruff` no están incluidos en `requirements.txt`; instálalos por separado en el entorno virtual si vas a ejecutar las comprobaciones:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest ruff
.\.venv\Scripts\python.exe -m pytest app/scratch/
.\.venv\Scripts\python.exe -m ruff check app/
.\.venv\Scripts\python.exe -m ruff format --check app/
```

Las pruebas con mocks no sustituyen la verificación con el cliente, la GPU, los controladores, los proveedores externos o una partida real. En particular, comprueba la captura de vídeo y audio en el equipo donde se usará la aplicación.

## Crear un ejecutable

El proyecto incluye una especificación de PyInstaller para Windows. Con PyInstaller instalado en `.venv`:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller main.spec
```

El resultado depende de las versiones instaladas de Python, PyInstaller y Qt. El repositorio no incluye un instalador firmado ni un canal de actualización publicado.

## Solución de problemas

| Problema | Qué revisar |
| --- | --- |
| No aparecen datos de perfil, selección o historial LCU | Abre el cliente de League, espera a que termine de cargar y comprueba que el proceso y su lockfile estén disponibles. |
| Partida en vivo sin datos | Confirma que hay una partida activa y que Live Client Data API responde en el equipo. |
| Falta el análisis de campeón o una variante | Comprueba campeón, línea, rango y caché local; después usa la acción de actualización con conexión. |
| No se inicia la grabación | Revisa FFmpeg, el filtro `ddagrab`, el encoder `h264_amf`, la carpeta de salida y los permisos. Consulta los diagnósticos de la aplicación. |
| El vídeo no muestra el monitor esperado | Verifica qué monitor contiene League al iniciar y el índice de monitor configurado. La selección no cambia al cambiar el foco. |
| La grabación no contiene sonido | Comprueba el modo, la fuente/dispositivo disponible y los diagnósticos. El backend no ofrece captura de audio por proceso; no asumas que «Solo juego» equivale a loopback exclusivo. |
| Falla la sincronización o Gemini | Comprueba la clave, configuración de cuenta, conexión, permisos y límites del proveedor correspondiente. |

## Limitaciones conocidas

- La interfaz está disponible en español y Windows es el único sistema operativo objetivo documentado.
- LCU es una interfaz interna y no estable del cliente de League; sus rutas y respuestas pueden cambiar.
- La compatibilidad de la grabación depende de las capacidades presentes en el FFmpeg y el hardware instalados. La captura selecciona un monitor completo y no excluye otras ventanas visibles en él.
- El backend actual no proporciona captura de audio por proceso de League. Las fuentes de audio tradicionales dependen de Windows y de los dispositivos configurados.
- Las estadísticas de campeones y objetos no garantizan resultados de partida y pueden quedar desactualizadas entre parches.

## Licencia y marcas

El repositorio no incluye un archivo de licencia. No presupongas que el código puede redistribuirse o reutilizarse sin autorización del titular. League of Legends, sus personajes, objetos y recursos pertenecen a Riot Games y sus respectivos propietarios. SOLRALOL es un proyecto independiente y no está respaldado por Riot Games.
