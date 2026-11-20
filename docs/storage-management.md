# Almacenamiento local de Solralol

`StorageManager` (`app/services/storage_manager.py`) es la referencia de rutas persistentes del backend. En Windows, el directorio inicial es `%USERPROFILE%\\.solralol`; el selector puede cambiarlo. El único puntero que queda fuera de esa raíz es `%APPDATA%\\Solralol\\storage.json`, con la ruta activa. Electron lo lee antes de crear ventanas y entrega la misma ruta a Python como `SOLRALOL_DATA_DIR`.

La estructura se adapta a los formatos ya usados por la aplicación:

- `settings.json`, `match_history_cache.json`, `live_match_sessions.json`
- `profiles/` (perfiles, historial LCU, análisis guardados y BattleScore)
- `recordings/videos/`, `recording-thumbnails/`
- `cache/` (campeones y catálogos editables), `ddragon/`, `meta/`
- `match_logs/`, `logs/`, y los directorios `matches/` y `analysis/` para nuevos datos
- `electron/` (preferencias locales del shell Electron)

Los catálogos incluidos con la aplicación siguen siendo recursos de solo lectura. Los datos generados y descargados se guardan en la raíz activa. La clave Riot y otros secretos siguen dentro del archivo de ajustes gestionado por el backend y nunca se exponen al renderer.

## Escrituras y migracion

Los JSON persistentes usan temporales unicos en el mismo directorio, flush/fsync, cierre previo y `os.replace` con reintentos acotados. Un cerrojo por archivo serializa hilos y procesos. Si falla la sustitucion, el archivo valido anterior permanece.

En Windows, la sincronización actual usa mutex del sistema sin crear `.lock` por grabación. Los locks heredados se retiran solo mediante un handle exclusivo con eliminación al cerrarse; un propietario activo o un handle de espera impide la limpieza. La biblioteca limita la recuperación a vídeos asociados y nombres generados por Solralol, incluso si su vídeo/JSON ya no existe. No usa la edad del lock. En POSIX se conservan los sidecars estables de `flock`. Véase `docs/recording-draft-live-regressions.md` para las pruebas Windows de concurrencia y crash.

El cambio de ubicacion ya no copia datos desde el backend activo. `storage.migrate.start` valida el destino, finaliza ordenadamente una grabacion activa y prepara un traspaso. Electron escribe una configuracion temporal en `%APPDATA%\Solralol\migrations\`, inicia una segunda instancia Electron independiente y espera su confirmacion antes de cerrar la aplicacion y el backend.

`migration-assistant.cjs` mantiene una ventana independiente y espera los PID concretos de Electron y Python que pertenecen a la operacion. `storage-migration-worker.cjs` copia en streaming a un staging hermano del destino, reusa archivos parciales solo si el tamano y SHA-256 coinciden, valida JSON critico y SQLite cuando hay bases de datos, y actualiza el puntero `%APPDATA%\Solralol\storage.json` solo tras verificar. El origen no se borra. Los errores y el ultimo estado quedan en el diario y en `migrations/<id>.log`; una nueva ejecucion puede reanudar el staging de la misma operacion. Un destino con archivos ajenos se rechaza sin sobrescribirlos.

En desarrollo, `start-electron.cjs` sigue vivo cuando cierra la ventana principal y consulta el diario hasta que el asistente pide iniciar con el origen o el destino. `scripts/dev.cjs` mantiene Vite y suspende los reinicios Electron durante ese estado. El asistente no depende de IPC ni del proceso Python despues del traspaso. Al arrancar la nueva ubicacion, Electron registra si el backend quedo listo; si no, el asistente permite restaurar el puntero al origen sin borrar ninguna copia.

La prueba automatizada del worker cubre una biblioteca de mas de 1 GiB con 3.000 archivos, MP4 disperso, verificacion SHA-256 y conservacion del origen; tambien cubre destino ajeno, reintento desde staging y cierre simulado antes del commit. La ventana Electron real, los bloqueos de Windows/antivirus y la migracion real entre unidades requieren validacion interactiva.

## Compatibilidad heredada

En desarrollo, `data/` continúa siendo la fuente de recursos incluidos; no es un directorio de escritura nuevo. Los servicios que leen iconos o metadatos heredados conservan una ruta de lectura de respaldo. Las nuevas descargas van a la raíz central. Los datos editables antiguos de campeones se copian sin sobrescribir archivos centrales existentes.

No se ha migrado el historial real ni las grabaciones del usuario en esta sesi?n. Las pruebas usan datos temporales, incluida una migración dispersa de m?s de 1 GiB. La prueba visual de Electron y la migración real entre unidades requieren validaci?n interactiva.
