# PLAN: Compras — elixires, "Según tus compras" y próxima compra

## Petición
1. Inventario con 6 objetos → las 3 recomendaciones pasan a ser los 3 frascos/elixires (2138 Elixir de hierro, 2139 Elixir de ira, 2140 Elixir de brujería), excluyendo los ya comprados.
2. Nueva sección "Según tus compras" en el panel (bajo las 3 recomendaciones, recuadro rojo): mejoras completables con componentes ya comprados. Ej: tener 3123 (Llamada del verdugo) → 3033 (Recordatorio mortal). Mostrar icono, nombre, qué falta y oro pendiente.
3. En cada tarjeta recomendada (zona recuadro verde): "Próxima compra" según el oro actual del snapshot (componente más barato de la receta que pueda pagar ya; si oro ≥ coste total → "Comprable ya").

## Estado
- Suite base OK: 30 tests en scratch/test_live_recommendations.py
- Comando tests: $env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONIOENCODING='utf-8'; Set-Location 'd:\Accesos\Desktop\Solralol'; & '.\.venv\Scripts\python.exe' -m unittest scratch.test_live_recommendations -v
- Catálogo: data/items.json (formato Data Dragon: root['data'][id] con gold.total, gold.base, from, into, tags, plaintext)
- Servicio: app/services/live_recommendation_service.py — puntos: __init__ carga catálogo; analyze() devuelve informe (recommendations/threats); _rank() corta a 3.
- Panel: app/ui/recommendation_panel.py — sección "3 objetos · Sinergia" con filas compactas; rivales a la derecha.
- Tests: scratch/test_live_recommendations.py (fixture snapshot con inventario y oro).

## Implementación
1) Servicio:
   - _rank: si inventario ≥ 6 objetos → recomendaciones = elixires 2138/2139/2140 no comprados, motivo "Inventario completo...".
   - _purchases(inventory): objetos del catálogo con 'from' donde posees ≥1 componente de su receta y no posees el objeto → {id, name, missing, gold, reason}; orden por menos piezas que faltar / coste; máx 3. Ej: 3123 → 3033.
   - _next_buy(item_id, inventory, gold): componentes que faltan (from − inventory); si oro ≥ total → "Comprable ya (totalg)"; si no → componente más barato asequible → "Puedes comprar <comp> (<g>)"; si nada asequible → "Faltan Xg para <comp>".
   - analyze(): report['purchases'] y cada recommendation['next_buy'].
2) Panel:
   - Sección "Según tus compras" bajo recomendaciones con filas compactas (icono, nombre, motivo, oro).
   - En cada tarjeta recomendada, línea "Próxima compra: <texto>".
3) Tests nuevos: elixires con inventario lleno; purchases 3123→3033; next_buy oro suficiente/insuficiente; UI (sección y línea de próxima compra). Luego suite LIVE completa + assets + draft.
