# Verificación manual del importador de runas

Las pruebas automatizadas simulan las respuestas LCU. Para comprobar que una
versión nueva del cliente acepta la página, sigue estos pasos en una sesión
de práctica o en la herramienta de selección de campeones:

1. Abre League of Legends y Solralol.
2. En Solralol, abre Análisis o Draft y elige una página que muestre nueve
   selecciones: keystone, tres runas principales, dos secundarias y tres
   fragmentos.
3. Usa «Importar build + runas» o la acción de importación de runas.
4. En el cliente, abre la página `Solralol - <campeón> Página <n>` y comprueba
   árbol principal, keystone, las tres filas menores, árbol secundario, las dos
   filas secundarias y los tres fragmentos.
5. Confirma que no aparecen indicadores de runa movida o selección inválida.
6. Repite la importación y verifica que se actualiza la página Solralol
   existente, sin borrar otras páginas ni crear una copia adicional.

El importador consulta `/lol-perks/v1/perks`, `/lol-perks/v1/styles` y
`/lol-perks/v1/pages` del cliente conectado. Después de escribir, vuelve a
leer las páginas y compara árboles e IDs antes de informar éxito. No se debe
probar modificando una página personal existente: el flujo crea o actualiza
únicamente una página editable con el nombre de Solralol.

Los fragmentos se validan por su ranura. El LCU observado permite repetir
Fuerza adaptable (`5008`) en ataque y flexibilidad, por lo que esa repetición
es válida si ambas definiciones de fila la permiten. Las runas de keystone,
filas principales y filas secundarias sí deben ser distintas.
