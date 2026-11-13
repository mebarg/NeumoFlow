# Tabla FVC por etapas

La tabla FVC se abre en **vista Total** de forma predeterminada. En
**Configuración → FVC → Vista de la tabla de maniobras** se puede elegir
**Total** o **Compacta**. La elección se guarda automáticamente y se recupera
al abrir la aplicación; el botón de la tabla también actualiza esa preferencia.

Ambas vistas conservan la misma altura de fila (26 píxeles), la fila de
predichos, las separaciones PRE/POST, todas las maniobras y los resúmenes al pie
de cada etapa. Compacta sólo oculta columnas secundarias; no oculta etapas ni
sus resúmenes. La tabla queda por encima de los gráficos y la división se
puede ajustar arrastrándola.

Las filas de resumen muestran los mejores valores de las maniobras incluidas
por fase, según el resumen existente. La presentación no cambia la inclusión,
los resultados ni las referencias de los estudios. Predichos, etapas y resúmenes
se distinguen con fondos propios, incluso bajo estilos de escritorio oscuros.

## Orden de las maniobras

Dentro de PRE y POST se muestran primero las maniobras con mayor **FVC + FEV1**.
Se usan los valores guardados completos, sin redondearlos para ordenar. En
empates se conserva el orden previo; si falta uno de ambos valores, la maniobra
queda al final de su etapa. La clasificación se aplica al abrir el estudio y
al incorporar una nueva captura, tanto en Total como en Compacta.

No se mezclan etapas ni se desplazan las filas de predichos o resumen. Las
horas, datos, inclusión y selección para imprimir conservan su identidad. Las
curvas mantienen sus colores según el orden de adquisición, independientemente
del lugar de la maniobra en la tabla. Una maniobra excluida puede aparecer
arriba por su valor, pero sigue excluida de los cálculos del sumario.

## Progresión PRE → POST

La etapa de adquisición pertenece al estudio y es compartida por FVC, SVC y
MVV. Al seleccionar POST se guarda `workflow.post_started=true` en los
metadatos del estudio, sin sustituir las referencias originales. Desde ese
momento PRE queda deshabilitado para nuevas capturas en las tres pantallas.

El bloqueo se conserva al cerrar/reabrir y al exportar/importar `.espiro`.
Un estudio anterior que ya contiene una maniobra POST (incluida, excluida o
incompleta; FVC/SVC/MVV) también abre en POST y conserva el bloqueo aunque se
eliminen esas maniobras. Un estudio nuevo comienza en PRE.

Las maniobras PRE anteriores permanecen visibles para revisar curvas y su
inclusión. Durante una captura tampoco se puede cambiar de etapa. Al iniciar
una captura se vuelve a comprobar la etapa guardada para evitar registrar una
nueva maniobra PRE en un estudio que ya pasó a POST.
