# Restricción de filtros de análisis — 5 de octubre de 2026

La definición única reside en `app/services/rangos_campeones.py`. La UI, generación, validación y adaptadores comparten sus valores derivados. Se conservan los JSON legibles y el esquema 2.

| Etiqueta UI | Clave local / Lolalytics | OP.GG | U.GG |
| --- | --- | --- | --- |
| Esmeralda | emerald | EMERALD | 16 |
| Esmeralda+ | emerald_plus | EMERALD_PLUS | 17 |
| Diamante | diamond | DIAMOND | 3 |
| Diamante+ | diamond_plus | DIAMOND_PLUS | 11 |
| Master | master | MASTER | 2 |
| Master+ | master_plus | MASTER_PLUS | 14 |

El valor inicial sigue siendo `emerald_plus`. Los rangos exactos incluyen su nivel; «+» incluye ese nivel y los superiores. Grandmaster y Challenger forman parte de los agregados, pero no son filtros seleccionables ni se generan individualmente.

Se eliminan las dos listas independientes de 17 rangos y las cadenas de sustitución U.GG. Desaparecen `all`, `iron`, `bronze`, `silver`, `gold`, `platinum`, `grandmaster`, `challenger`, `gold_plus`, `platinum_plus` y `diamond_plus_100`. Se corrigen además los códigos U.GG: Diamond y Master tenían códigos incorrectos; Diamond+ y Master+ reutilizaban Emerald+. Los códigos nuevos proceden de la enumeración del JavaScript público U.GG inspeccionada en `scratch/ugg_main.js`.

Los seis parámetros OP.GG se comprobaron contra su [endpoint público](https://lol-api-champion.op.gg/api/global/champions/ranked/aatrox/top?tier=EMERALD_PLUS). En la muestra observada de Aatrox: Emerald 92.690, Diamond 44.644 y Master+ 26.837 partidas; su suma coincide con Emerald+ (164.171). Diamond + Master+ coincide con Diamond+ (71.481); Master exacto tenía 24.732. Lolalytics también distingue el [filtro Diamond+](https://lolalytics.com/lol/aatrox/build/?tier=diamond_plus).

## Limpieza y seguridad

La primera lectura de un documento antiguo normaliza alias ingleses como `Emerald+`, `EMERALD_PLUS` y `Emerald Plus`, elimina rangos obsoletos y sus resúmenes globales identificados, valida y reemplaza atómicamente mediante temporal único, fsync y `os.replace`. Los datos canónicos compatibles se mantienen. No hay redescarga ni barrido nuevo obligatorio en el constructor; el catálogo de inicio ya lee perfiles y por ello aplica la misma limpieza. Cada actualización crea una matriz nueva de seis rangos. Guardar claves obsoletas se rechaza; consultar un filtro no compatible devuelve `UNSUPPORTED` antes de leer el archivo.

Una colisión entre alias con datos contradictorios o una variante compatible mal formada impide sobrescribir el archivo. Las instancias del repositorio comparten un cerrojo para coordinar limpieza y actualización dentro del proceso; el trabajo remoto se realiza fuera de él. Las cachés se invalidan tras guardar y reconocen reemplazos externos por revisión del archivo.

La limpieza realizada verificó primero los 173 archivos y la igualdad de sus bloques compatibles; después depuró ocho: Aatrox, Ahri, Akali, Akshan, Alistar, Ambessa, Amumu y Anivia. Todos se releyeron y verificaron. No se regeneró contenido remoto.

## Mediciones

| Medición | Antes | Después |
| --- | ---: | ---: |
| Aatrox JSON | 691.318 bytes | 238.873 bytes |
| Conjunto de 173 JSON | 6.253.035 bytes | 2.746.037 bytes |
| Lectura y deserialización Aatrox, mediana de 30 | 5,63 ms | 1,96 ms |

La consulta local con caché midió 0,34 ms de mediana sobre 100 consultas. Aatrox se reduce aproximadamente un 65,4%; el conjunto, un 56,1%. No se introduce compresión. Valores completos en `medicion_rangos_campeones.json`.

## Generación, UI y validación

«Actualizar campeón» y «Actualizar todos» usan el mismo bucle canónico de seis rangos; progreso por rango = etapas 1/6 a 6/6. El progreso global continúa contando campeones. Los JSON de overview/builds de U.GG son respuestas indivisibles que incluyen todos sus niveles externos; solo se procesan los seis bloques permitidos. OP.GG y Lolalytics reciben únicamente parámetros compatibles.

La navegación normal conserva consultas locales y los estados vacíos existentes, sin descarga automática. La prueba de 60 consultas alternando los seis filtros observa una sola deserialización y bloquea cualquier petición HTTP. Se comprueban el selector Qt real, los adaptadores, ambos botones, progreso, normalización, conservación, conflictos, escritura fallida y caché entre repositorios.

Validación final: `python -m pytest app/scratch/ -q`: **80 pruebas superadas**. Ruff pasa en la configuración, repositorio, adaptador, servicio local, pruebas y scripts afectados; los 17 archivos Python modificados pasan la comprobación de formato. UI y scraping mantienen incidencias de lint heredadas fuera de este cambio. `git diff --check` pasa. Se volvieron a validar los 173 JSON: ningún filtro obsoleto y todas las identidades y variantes compatibles.

## Archivos del cambio

- Nuevo: `app/services/rangos_campeones.py`.
- Servicios: `repositorio_campeones.py`, `champion_scraper_service.py`, `champion_variant_service.py`, `analisis_local_service.py`.
- UI: `app/ui/local_analysis_dialog.py`, `app/ui/champion_scraper_worker.py`.
- Pruebas: `app/scratch/test_rangos_campeones.py` (nuevo), `test_repositorio_campeones.py`, `test_carga_analisis_local.py`.
- Scripts de ensayo ajustados a rangos compatibles: `app/scratch/build_matrix.py`, `validate_rank_changes.py`, `validate_variants.py`, `probe_lane_rank.py`, `debug_ugg_all_ranks_runes.py`, `debug_ugg_gold_runes.py`, `debug_ugg_gold_pd.py`. Los dos últimos conservan su nombre histórico.
- Documentación: `AGENTS.md`, este informe y `app/scratch/medicion_rangos_campeones.json`.
- Datos: los ocho JSON depurados en `data/champion_data/`.

No se modifica README ni se realizan commits. Los datos compatibles existentes se conservan; las próximas actualizaciones emplean el mapeo corregido de proveedores.
