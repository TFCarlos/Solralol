# Ajustes de análisis y BattleScore

La configuración editable de BattleScore se guarda en `analysis/analysis_settings.json`, dentro del directorio de datos elegido por el usuario. El archivo usa `schema_version` y `configuration_version`; cada resultado calculado guarda además el motor, revisión, huella de configuración y cobertura de telemetría.

El backend valida la configuración completa antes de activarla y la escribe de forma atómica. Conserva la última versión válida como `analysis_settings.json.bak`. Si el archivo principal no se puede leer, recupera esa copia; si tampoco es válida, preserva el archivo dañado con sufijo `.corrupt.<marca de tiempo>` y crea una configuración inicial desde los valores efectivos del motor. La pantalla de Ajustes informa de la recuperación.

Al guardar, el backend publica una instantánea inmutable y programa un único recálculo en segundo plano de partidas que ya tienen BattleScore activo. Solo usa Match-V5 y cronologías guardados; no modifica el payload original ni vuelve a descargar datos. La persistencia de cada resultado verifica que la revisión siga siendo la actual. Un cambio de configuración durante un recálculo sustituye los resultados obsoletos y vuelve a procesar el lote con la última revisión.

Los gráficos reciben el intervalo y suavizado configurados, pero el motor conserva su cronología canónica completa a resolución propia. El muestreo visual nunca participa en el cálculo de la puntuación.

Las fuentes se muestran desde un registro validado de campos y semánticas. En esta versión son explicativas de solo lectura: no se permite introducir campos Riot arbitrarios ni cambiar a un fallback con semántica distinta. Los componentes de puntuación sí pueden activarse o desactivarse.

`analysis_limits.max_active_matches` limita nuevas activaciones (rango admitido: 1–100). Reducirlo no desactiva ni borra análisis existentes; los controles de partidas guardadas permiten retirar análisis individualmente con la acción explícita del usuario.

## Oportunidades de mejora

Los hallazgos negativos están separados de los logros positivos y no modifican BattleScore. Sus umbrales de gravedad, duración mínima, roles y factores por posición viven en `negative_achievements.rules`; la sección también permite ocultar todos los hallazgos o solo los leves. Las categorías que dependen de atribución individual no disponible permanecen registradas y bloqueadas para activación.

Las reglas disponibles usan estadísticas Match-V5 para visión, economía, combate, supervivencia y presión de estructuras. Los déficits tempranos de oro/XP y las muertes iniciales requieren frames/eventos de timeline y un rival de la misma posición; si faltan esos datos, no producen un hallazgo. Los umbrales iniciales son valores configurables de respaldo, no una distribución validada de Emerald+.

Al guardar cambios de logros, los análisis activos se vuelven a evaluar en segundo plano desde telemetría local. La ventana ya abierta actualiza solo los dos paneles de logros mediante `soloq_analyses.achievements`; no reconstruye BattleScore ni solicita datos a Riot para este refresco.
