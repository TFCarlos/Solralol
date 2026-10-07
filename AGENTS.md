# Solralol: instrucciones para agentes

## Propósito y uso de este documento

Este archivo es la referencia persistente para desarrollar Solralol. Leerlo al iniciar una tarea y consultarlo cuando falte contexto. Las instrucciones actuales del usuario prevalecen sobre este documento. Verificar los detalles contra el código antes de asumir que el mapa del proyecto sigue vigente.

Mantener este archivo actualizado cuando una tarea cambie la arquitectura, los comandos, los flujos de datos o las convenciones. Registrar únicamente información comprobada y decisiones duraderas. No guardar claves, credenciales, datos privados de jugadores ni conversaciones completas. La actualización de este documento está autorizada como parte del mantenimiento del proyecto.

Las peticiones de cambios autorizan las refactorizaciones, renombrados y reorganizaciones necesarios para realizarlos. Por ejemplo, cambiar el estilo de la aplicación, añadir una función o modificar una ventana permite adaptar el código y la estructura implicados sin pedir permiso adicional. Una petición «Optimiza X» autoriza todos los cambios necesarios sobre X y sus dependencias, siempre que la aplicación siga funcionando y se compruebe la mejora de rendimiento. No extender el alcance a cambios ajenos a la petición.

Si el usuario indica «tienes control total», quedan autorizados todos los cambios necesarios para cumplir la petición sin consultas adicionales, excepto los commits a Git. Los commits requieren una instrucción explícita independiente. Esta autorización no elimina los controles de permisos del entorno. Preguntar únicamente si falta información imprescindible para determinar el resultado solicitado.

## Objetivo del producto

Aplicación de escritorio para Windows que acompaña partidas de League of Legends, con Python y PySide6. Combina tres fases:

El objetivo central es generar un sistema de análisis que ayude al jugador a identificar y solucionar sus errores durante la partida o el draft. Las métricas y recomendaciones deben explicar qué decisión puede mejorar, por qué y cómo corregirla; el análisis posterior debe ayudar a aprender de esos errores.

- Prepartida: selección de campeones, composiciones, emparejamientos, estadísticas y recomendaciones; importación de runas, objetos y hechizos mediante LCU.
- En partida: métricas, eventos, objetivos, recomendaciones, overlay y grabación automática.
- Postpartida: historial, sincronización con Riot, análisis del rendimiento y reproducción de vídeo con marcadores.

Priorizar estabilidad durante la partida, baja latencia y una interfaz que permita entender lo importante de un vistazo. Distinguir datos observados, estimaciones y recomendaciones. No presentar como medibles datos que la API no proporciona.

## Mapa actual del repositorio

- `app/ui/`: ventanas, componentes Qt y workers existentes asociados a la interfaz. `local_analysis_dialog.py` contiene el análisis local; `draft_tool_dialog.py`, la selección; `live_match_analysis_dialog.py`, el análisis en vivo; `postgame_replay_window.py`, la reproducción posterior.
- `app/ui/draft_tool_dialog.py` importa runas, build y hechizos desde el repositorio local (`RepositorioCampeones`) en el rango `Esmeralda+`, sin red al navegar: solo relee al cambiar campeón, línea o rango; los cambios de rival solo repintan la build. `DraftAnalyzerService.normalizar_hechizos` centraliza las reglas de hechizos por línea. Las dos páginas de runas son clicables (`TarjetaPaginaRunas`), con selección visible, tarjeta de estado inline (`MensajeEstado`), importación combinada build+runas e independiente de hechizos mediante `run_async`, sin `QMessageBox`. Los botones conservan tamaño con texto (`… Importando...`/`✓ Importado`/`⚠ Error`), token de contexto contra resultados obsoletos e ignoran clics rápidos. Los bans LCU (`session.actions[type=ban]` por `cellId/isAllyAction`) pueblan diez huecos explícitos por equipo con acento propio; el WR usa texto `ventaja/texto` tras aislar `QLabel[estado]` en `estilo_global.py`.
- `app/ui/barra_lateral.py` presenta los siete destinos globales, el logo `data/LogoApp.png` y la marca plegable. El control inferior separado anima el ancho entre 248 y 84 px durante 240 ms. `main_window.py` dispone esta navegación junto a las páginas existentes; la cabecera exterior contiene únicamente estado y cierre.
- Home usa `app/ui/home_dashboard.py` y `app/services/home_history_service.py`. Perfil e historial LCU se leen en segundo plano sin Riot REST API; la colección se consulta en una tarea independiente para que no retrase la actualización del historial. El repositorio JSON local separa cuentas por SHA-256 del PUUID (o `summonerId` como respaldo) bajo `~/.solralol/profiles/<id_hash>/`, conserva esquemas no compatibles sin sobrescribirlos y no poda partidas automáticamente. La lista de historial mantiene scroll interno, aumenta su altura con el viewport y carga 25 partidas por lote. Cada `gameId` se enriquece desde `/lol-match-history/v1/games/{gameId}` si faltan participantes completos o una resolución fiable de rival; almacena posiciones, aliados, confianza/método del rival y el estado exact/probable/ambiguous/unavailable. La resolución versión 4 compara posiciones explícitas, conserva rivales fiables y usa el orden de picks top/jungle/mid/bot/support como respaldo determinista; actualiza el rival/equipo sin sustituir participantes completos ni duplicar la partida. La normalización de roles es compartida y distingue carry/support; Smite solo respalda la inferencia de jungla. El historial muestra el rival directo únicamente en estados exacto/probable y, si es ambiguo, los iconos del equipo con el excedente agrupado; los diagnósticos agregados no incluyen identificadores personales. Enfrentamientos se agregan por ID canónico de campeón y partida, filtran confianza menor a 0,75 y mantienen rankings disjuntos; las columnas se reubican con los mismos widgets según el ancho. Compañeros se ordenan por partidas y recencia, con identidad visual desde caché local o campeón más jugado juntos y retrato enmarcado por separado. Los paneles inferiores comparten una altura mínima moderada y crecen según el contenido; la distribución reserva aproximadamente 40/35/25 para compañeros/enfrentamientos/colección en escritorio. El worker comunica progreso y conserva resúmenes históricos si el detalle deja de estar disponible. Los enlaces a sesiones guardadas se persisten en `saved_match_link` y la insignia de Home reutiliza `open_saved_game_analysis`. La interfaz dibuja retratos e iconos solo desde caché local. Maestría, campeones, skins, desafíos y títulos son consultas LCU opcionales; ownership solo se cuenta con confirmación explícita y los datos válidos se conservan localmente. Las clases y nombres de campeón salen de `data/champion_metadata/` sin red.
- `app/ui/sistema_visual.py` centraliza la paleta derivada del logo (ocre, marfil y marrón oscuro), espacios y radios; `estilo_analisis.py` genera los estilos Qt. `superficies_analisis.py` pinta el fondo abstracto y el héroe, y recorta los iconos. El análisis conserva las pestañas de edición, apila grupos por debajo de 1180 px y filtros, acciones y páginas de runas por debajo de 1100 px. Los situacionales se agrupan en una cuadrícula de dos columnas. Las acciones permanecen dentro del héroe y accesibles cuando faltan datos.
- El splash opcional del héroe se lee en el worker local desde `data/champion_splashes/<identificador_Data_Dragon>_0.jpg` (también admite PNG/WebP), con la caché de recursos existente y sin peticiones al seleccionar. Si falta o falla su lectura, se usa el degradado. La actualización explícita asegura el splash mediante `data_dragon.get_champion_splash_path` (descarga validada con guardado atómico y origen en `origenes.json`), sin abortar los datos si falla. El arte se recorta a la tarjeta con superposición oscura; el fondo global no admite ilustraciones.
- El análisis local usa `app/ui/analisis_local_worker.py` y `app/services/analisis_local_service.py`: una cola Qt sin retardo artificial aplica únicamente la última generación de selección. Navegar por campeón, línea o rango consulta datos locales, incluidos iconos y metadatos, sin descargar ni recalcular recomendaciones. La ausencia local muestra un estado vacío con actualización explícita. Los botones de actualización del héroe tienen dimensiones fijas (210x36) y un contenedor de estado reservado, con estado `cargando` sin cambios de tamaño.
- `app/services/repositorio_campeones.py` centraliza `data/champion_data/<identificador>.json`, con `schema_version = 2`, perfil global y matriz `ranks[rango][línea]`. Valida documentos, distingue ausencia/falta de muestra/incompatibilidad/corrupción/fallo de actualización y usa temporal único, fsync y reemplazo atómico. Mantiene ocho documentos en caché y detecta cambios por fecha de modificación y tamaño; la consulta copia solo perfil y variante solicitados. El servicio local conserva hasta dieciséis preparaciones de vista por revisión del archivo.
- `app/services/rangos_campeones.py` define los únicos filtros de análisis: `emerald`, `emerald_plus`, `diamond`, `diamond_plus`, `master`, `master_plus`, con etiquetas Esmeralda, Esmeralda+, Diamante, Diamante+, Master y Master+. El valor inicial es Esmeralda+. UI, validación y generación usan esta configuración; los códigos U.GG son respectivamente 16, 17, 3, 11, 2 y 14, sin sustitución entre filtros. OP.GG y Lolalytics tienen parámetros separados. Los agregados «+» incluyen el nivel indicado y los superiores, sin exponer estos últimos como filtros individuales. El repositorio depura y normaliza archivos antiguos al leerlos, valida antes del reemplazo atómico y conserva archivos contradictorios sin sobrescribirlos. Las instancias comparten un cerrojo durante las operaciones locales para coordinar limpieza, lecturas y actualizaciones; la generación remota queda fuera del cerrojo.
- `app/services/preparador_datos_campeon.py` genera recomendaciones al migrar o actualizar. `ChampionScraperService.actualizar_todo` y `ChampionScraperWorker` regeneran matrices completas tanto para «Actualizar campeón» como para «Actualizar todos», con progreso, cancelación y conservación de datos válidos ante fallos. El progreso usa porcentajes 0..100 con etapas reales (rangos, recursos, guardado) en modo un campeón y recuento monótono de campeones en modo global; el 100 solo se emite tras persistir. No se generan análisis al arrancar.
- Los metadatos estáticos de Data Dragon residen en `data/champion_metadata/`, separados de las matrices; las habilidades continúan en `data/champion_abilities/`. La migración verificó 173 perfiles y diez variantes antes de eliminar el almacén monolítico. Draft, recomendaciones live, editor y cálculo de enfrentamientos consumen perfiles del repositorio. `app/services/catalogo_analisis_local.py` comparte la resolución de objetos; el renderizado recibe bytes de imágenes locales.
- `app/ui/contenedores_analisis.py` agrupa títulos, contenido y pies de matchups y recomendaciones en tarjetas de altura natural. La tabla ajusta filas al texto y al ancho, también tras ordenar; todo su contenido usa el scroll principal del análisis.
- `app/services/`: acceso a APIs, lógica analítica, recomendaciones, persistencia, grabación y servicios de segundo plano.
- `app/models/` y `app/utils/`: paquetes auxiliares existentes.
- `app/scratch/`: ubicación obligatoria para nuevas pruebas, fixtures y scripts de ensayo.
- `data/`: catálogos, iconos, configuración y datos locales existentes.
- `main.py`: entrada actual de la aplicación. `_paths.py`: rutas de desarrollo y empaquetado. `data_dragon.py`: utilidades existentes de Data Dragon.
- `README.md`: descripción ampliada, configuración y flujos. `requirements.txt`: dependencias. `main.spec`: empaquetado con PyInstaller.

La estructura existente usa `app/services/`, no `app/service/`. Se puede reorganizar cuando la petición lo justifique, actualizando importaciones, pruebas y referencias afectadas. Toda nueva lógica de aplicación debe residir bajo `app/`; los archivos raíz existentes son compatibilidad heredada. Para nuevos modelos, usar `app/data/` cuando corresponda; para lógica común reutilizada por varios servicios, usar `app/common/` o un módulo común dentro de `app/services/`. No crear abstracciones sin una necesidad real.

## Fuentes de datos y límites entre capas

La aplicación es de uso personal y no comercial. El scraping web de otras herramientas forma parte de su estrategia de adquisición de datos, junto con las APIs: mantener y ampliar los scrapers cuando lo requiera la tarea. Contemplar cambios de formato, datos incompletos, caché y frecuencia de consultas para que los fallos de una página no bloqueen el análisis.

- Live Client Data API: `https://127.0.0.1:2999/liveclientdata/allgamedata`, disponible durante una partida.
- LCU: HTTP o WebSocket local; obtener credenciales del lockfile. Tratar la ausencia del cliente como un estado normal.
- Riot REST API: perfil, historial y sincronización posterior mediante clave API; gestionar límites de peticiones y fallos transitorios.
- Data Dragon: catálogos e iconos. U.GG, OP.GG y Lolalytics: fuentes externas existentes de estadísticas y builds; comprobar formatos y vigencia antes de modificarlas.
- Gemini: análisis opcional mediante los servicios existentes; la aplicación debe seguir funcionando sin esa integración.

La UI solicita datos a servicios y no realiza peticiones HTTP directamente. Separar presentación, adquisición y cálculo. Ejecutar operaciones bloqueantes fuera del hilo gráfico mediante los mecanismos de workers existentes o soluciones asíncronas compatibles con Qt. No introducir un segundo modelo de concurrencia sin necesidad.

Definir tiempos de espera, cancelación cuando corresponda y gestión de errores. No desactivar globalmente la verificación TLS: cualquier excepción para endpoints locales debe quedar limitada a esos clientes. No exponer claves ni contraseñas del lockfile en logs o pruebas.

## Convenciones de código

- Escribir nuevos nombres propios de variables, funciones, métodos, clases, módulos y excepciones en español. Documentación y mensajes al usuario también en español.
- Conservar nombres impuestos por Python, Qt y bibliotecas externas, métodos sobrescritos, claves de las APIs y contratos de datos. No traducirlos si rompe la interoperabilidad. Renombrar identificadores propios existentes cuando forme parte del cambio autorizado, actualizando sus referencias.
- Añadir tipos completos a todas las firmas nuevas o modificadas, incluido el retorno.
- Cada función o método nuevo o modificado debe incluir un docstring breve en español que explique su propósito, parámetros y retorno.
- No añadir comentarios dentro del cuerpo de funciones ni comentarios de línea; usar nombres descriptivos y docstrings. No limpiar comentarios heredados fuera del alcance solicitado.
- Aplicar responsabilidad única y evitar duplicaciones. Mantener componentes acotados y dividir clases existentes cuando sea necesario para el cambio autorizado, sin pedir una confirmación adicional por la extensión de la refactorización.
- Transformar JSON externos en estructuras claras y validar campos ausentes o tipos inesperados. Evitar que errores de red o datos incompletos bloqueen la aplicación.

## Datos de juego y UX

Relacionar métricas con decisiones útiles: ventaja de oro, progresión, objetivos, composición, emparejamientos y picos de poder. Documentar en funciones las suposiciones de las estimaciones. Verificar con fuentes primarias los comportamientos de APIs y las reglas del juego que puedan haber cambiado.

Mantener jerarquía visual clara y baja carga cognitiva. Usar verde, rojo y amarillo para ventaja, desventaja y neutralidad, acompañados de texto o valores. Mostrar estados de carga, desconexión y datos no disponibles. No sustituir datos desconocidos por ceros que aparenten certeza.

## Estilo visual aprobado para toda la aplicación

El análisis local y el shell actuales son la referencia visual aprobada. Aplicar una dirección similar a las nuevas pantallas y a las existentes cuando se modifiquen: estética cyberpunk oscura y premium, oro envejecido, marfil y superficies cálidas sobre negro y azul carbón. Conservar esta identidad en refinamientos; extenderla progresivamente dentro del alcance de cada tarea, sin rediseñar pantallas ajenas a la petición.

- Reutilizar los tokens de `app/ui/sistema_visual.py` como fuente única. Paleta de referencia: base `#05070c`, superficie `#10151e`, elevada `#19202a`, marrón cálido `#1a0f0b`, oro principal `#b69a50`, oro suave `#d0bb7b`, oro oscuro `#544326`, marfil `#e1dab2`, texto `#eee8d8` y secundario `#afa99c`. El logo `data/LogoApp.png` define la identidad; su ocre `#ccaf42` no sustituye el oro principal de los controles. Evitar amarillo fluorescente, lima y colores arbitrarios por pantalla. Reservar teal y magenta para acentos discretos y mantener los colores semánticos de ventaja y desventaja acompañados de texto.
- Usar fondos abstractos con degradados oscuros, iluminación ocre/teal tenue y retícula discreta, siguiendo `FondoTecnologico`. No usar escenas o ilustraciones como fondo global. El splash de campeón solo puede aparecer dentro de su tarjeta, recortado a sus esquinas y oscurecido con un degradado que garantice la lectura; si falta, conservar el fondo sin arte.
- Mantener la navegación lateral plegable: logo y SOLRALOL al expandir, solo logo al plegar, iconos descriptivos, tooltips y estado activo claro. El control de plegado pertenece al área inferior separada. No duplicar la marca fuera de la barra ni convertir cada icono en un botón cuadrado con borde fuerte.
- Crear jerarquía mediante superficies, tipografía y separación. Las secciones principales tienen mayor presencia; las subtarjetas usan bordes más suaves y las filas principalmente separadores. Las tarjetas equivalentes comparten estilo, borde completo, radio y padding. Reutilizar `estilo_analisis.py`, `espaciar_tarjeta` y los componentes existentes cuando corresponda, evitando copias divergentes y bordes intensos en todas las cajas.
- Usar como referencia padding de 20 px en tarjetas normales y 12 px en compactas, separación interna de 12 px, entre secciones de 18 px, radio principal de 16 px e iconos de 8 px. Adaptar mediante tokens compartidos; títulos, retratos, gráficos y texto deben respirar dentro del contenedor. Enmarcar los iconos sin deformarlos, recortar esquinas ni superponerlos al borde exterior.
- Mantener Segoe UI y una jerarquía legible: título destacado, subtítulo, valores importantes, etiquetas y metadatos secundarios. Preferir marfil para datos y oro para énfasis. Agrupar métricas relacionadas horizontalmente cuando haya espacio; conservar el héroe compacto, los win rates próximos al título y las acciones alineadas dentro de su tarjeta. No ahorrar espacio reduciendo excesivamente la letra ni amontonando valores en una frase.
- Selectores y botones comparten alturas, radios, flechas alineadas y estados de hover, foco y pulsación. Usar superficies oscuras y acentos de oro cálido con brillo contenido. Mantener microinteracciones cortas y económicas, de aproximadamente 120–220 ms; la barra usa el token de 240 ms. Evitar animaciones continuas, desenfoques costosos y efectos distractores. Scrollbars finos, integrados y visibles.
- Los contenedores dinámicos deben crecer con el contenido. Incluir títulos, listas y pies dentro de su tarjeta; permitir ajuste de texto y recalcular filas de tablas al cambiar ancho u orden. No usar alturas fijas ni ocultar o truncar información útil para disimular desbordamientos. Priorizar el scroll principal y recurrir a scroll interno solo con una necesidad clara. Verificar tamaño de escritorio, ancho reducido y tamaño maximizado, con datos extensos y estados vacíos/cargando.
- Conservar toda la funcionalidad y visibilidad de datos al aplicar el estilo: controles, runas, builds, situacionales, gráficos, matchups, recomendaciones y estados de actualización. El cambio visual no debe alterar contratos de datos ni añadir trabajo bloqueante al hilo gráfico.

## Pruebas y validación

Cada función o método de producción creado debe tener cobertura automatizada correspondiente en `app/scratch/`. Al cambiar el comportamiento o firma de una función existente, crear o actualizar sus pruebas en la misma tarea. Usar pytest y mocks o fixtures para APIs, lockfile, archivos y otros recursos externos; las pruebas no deben necesitar una partida activa, claves reales ni red.

Comandos desde la raíz, preferiblemente con el intérprete de `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pytest app/scratch/
.\.venv\Scripts\python.exe -m pytest app/scratch/ -s -v
.\.venv\Scripts\python.exe -m ruff check app/
.\.venv\Scripts\python.exe -m ruff format --check app/
.\.venv\Scripts\python.exe main.py
```

`pytest` y `ruff` no figuran actualmente en `requirements.txt`; comprobar su disponibilidad antes de usarlos. Si faltan, informar y gestionar su instalación según los permisos disponibles. No declarar comprobaciones como superadas si no se ejecutaron.

Aplicar `ruff format` únicamente a los archivos del cambio para evitar reformatear todo el proyecto. Ejecutar pruebas relevantes y ampliar la validación si existen riesgos de integración. El comando `python -m app.main` no corresponde a la estructura actual; usar `main.py` hasta que se autorice cambiar la entrada.

Los cambios exclusivamente documentales no requieren pruebas unitarias: verificar contenido, rutas y comandos. No arrancar la aplicación ni conectarse a servicios externos solo para validar documentación.

## Skills y herramientas

Ponytail está disponible únicamente para este repositorio mediante `.agents/plugins/marketplace.json` (catálogo `solralol-local`) y activado en `.codex/config.toml`. Su copia local reside en `.agents/plugins/ponytail/`. Tras instalarlo o actualizarlo, iniciar una sesión nueva de Codex; los hooks requieren Node.js y la confianza del cliente. Las instrucciones de Solralol prevalecen sobre las recomendaciones de Ponytail, incluidas las convenciones de español, docstrings y pruebas.

Consultar el catálogo de skills disponible en la sesión y leer el `SKILL.md` de la skill elegida antes de aplicarla. No fijar rutas de instalación o versiones en este archivo: pueden cambiar entre equipos y sesiones. Informar al usuario la primera vez que se use una skill. Este documento no instala skills ni garantiza que estén disponibles.

- Desarrollo Python, servicios y pruebas: usar herramientas de repositorio, búsquedas con `rg` y el entorno virtual; no requiere una skill adicional del catálogo actual.
- `computer-use:computer-use`: si la tarea exige operar o verificar visualmente la aplicación mediante las superficies disponibles. Comprobar que el entorno permite controlar la aplicación necesaria.
- `imagegen`: creación o edición solicitada de recursos bitmap; no sustituir componentes Qt ni iconos vectoriales existentes por imágenes sin necesidad.
- `visualize:visualize`: explicaciones interactivas o exploración de métricas en la conversación. Para gráficos exportables o científicos, usar herramientas de gráficos y artefactos independientes.
- `openai-docs`: dudas sobre Codex, sus instrucciones, skills o productos y APIs de OpenAI. No es necesaria para el desarrollo ordinario de Solralol ni para Gemini.
- `skill-creator`: solo si se pide crear o modificar una skill reutilizable. `AGENTS.md` es documentación del repositorio, no una skill.
- `skill-installer` y `plugin-management:plugin-management`: cuando se solicite instalar skills o gestionar integraciones, o falte una integración necesaria.
- Skills de documentos, PDF, presentaciones y hojas de cálculo: solo cuando se pidan esos artefactos o su análisis.
- Skills de Sites y mascotas: no aplican al desarrollo habitual de esta aplicación de escritorio.

Si falta una skill opcional, continuar con las herramientas adecuadas disponibles y explicar la limitación cuando afecte al resultado. No delegar en subagentes salvo solicitud expresa del usuario o instrucciones aplicables que lo requieran.

## Flujo de trabajo y mantenimiento

1. Leer este archivo, la petición vigente y los módulos implicados; revisar el estado de Git para preservar cambios del usuario.
2. Concretar el cambio dentro del alcance autorizado, incluidas las refactorizaciones, renombrados y reorganizaciones necesarios. Respetar la autorización ampliada de «Optimiza X» y «tienes control total». Pedir aclaración solo si falta una decisión imprescindible.
3. Implementar junto con pruebas aisladas cuando haya cambios de código.
4. Validar y comunicar qué cambió, qué se comprobó y qué limitaciones quedan.
5. Actualizar este documento si cambió información duradera del proyecto. No convertirlo en un registro exhaustivo de cada tarea.
6. Después de terminar los cambios, preguntar al usuario si desea añadir al `README.md` la documentación de lo realizado. No modificar el README antes de recibir su respuesta, salvo que su actualización ya estuviera solicitada expresamente. Esta consulta se realiza al finalizar y no retrasa los cambios ni su validación.

Referencia inicial contrastada con el repositorio: 4 de octubre de 2026.
