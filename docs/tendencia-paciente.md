# Historial y tendencia del paciente

Al abrir un paciente, la ficha muestra las pestañas **Estudios** y **Tendencia**.
La primera conserva la lista habitual para abrir estudios o crear uno nuevo.
La segunda muestra una tabla cronológica por estudio y fase PRE/POST, y tres
gráficos configurables, inicialmente FEV1, FVC y PEF. Los selectores también
ofrecen FEV1/FVC, FEF 25–75, SVC, IC, ERV y MVV.

- La columna **Graficar** permite elegir los estudios que se dibujan. Todos
  empiezan marcados al cargar el historial. Las casillas PRE/POST de una misma
  visita se sincronizan: desmarcar una oculta ambas fases de ese estudio en
  los tres gráficos, conservando las filas para volver a marcarlo. Es una
  selección de visualización y no modifica la inclusión de maniobras ni los
  resultados guardados. Los estudios desmarcados se omiten de las series.
- PRE se representa con círculos azules; POST, cuadrados verdes. Ambos pueden
  ocultarse mediante sus casillas. La fase se indica también en cada fila.
- El eje horizontal representa tiempo real. Una misma fecha puede tener varios
  estudios y las visitas no se fusionan. La tabla y las ayudas muestran hora
  y segundos; la ayuda de cada punto incluye el ID del estudio. Las etiquetas
  del eje corresponden únicamente a visitas con puntos graficados, sin fechas
  intermedias inventadas. Cuando están muy próximas se omiten algunas etiquetas
  para que no se superpongan; los puntos y sus ayudas permanecen disponibles.
- Seleccionar un punto selecciona su fila y resalta esa visita/fase en los tres
  gráficos. Doble clic en una fila, o **Abrir estudio seleccionado**, abre el
  estudio. La consulta de la tendencia por sí misma no inicia el dispositivo.
- La división entre tabla y gráficos se puede arrastrar para ajustar el espacio.
- Las visitas sin resultados incluidos aparecen con valores ausentes. Un dato
  ausente o una fase no disponible corta la línea de esa serie; no se reemplaza
  por cero ni se interpola el dato faltante. Una sola visita se muestra como punto.

## Magnitudes y conservación de resultados

Se muestran valores absolutos. FEV1/FVC se expresa en porcentaje y PEF/FEF en
L/s. No se recalculan BTPS ni ecuaciones de referencia. Se identifica el origen
NeumoFlow/Breeze y la referencia de cada estudio; la ayuda de la fila explica
las ecuaciones guardadas cuando están disponibles. Comparar valores absolutos
no implica que los estudios tengan la misma referencia, equipo o calidad.

Para FVC sólo participan maniobras con `review_status=accepted`. El sumario y
la tendencia comparten `app.history.fvc_summary`: máximas FVC y FEV1 por fase,
cociente entre ambas, y máximos FEF 25–75/PEF, conforme al comportamiento del
sumario existente. La tendencia no incorpora automáticamente maniobras pendientes,
excluidas ni rechazadas.

SVC/IC/ERV/MVV usan el mismo resumen de mediciones incluidas que el sumario:
SVC/MVV máximas, IC promedio de las SVC válidas incluidas, ERV de la mayor SVC.
La estimación provisional de una MVV incompleta no se grafica como MVV.

La consulta no modifica pacientes, sesiones, referencias o maniobras. Se recarga
al volver a la ficha del paciente. Se conserva la pestaña al volver al mismo
paciente y se vuelve a Estudios al cambiar de paciente para evitar mostrar un
historial anterior. No requiere migración de base de datos ni dependencias nuevas.

## Comprobación

Pruebas con bases temporales cubren orden temporal y zonas horarias, separación
PRE/POST y pacientes, visitas vacías, selección de maniobras, referencias Breeze
sin cambios, SVC/MVV, navegación desde puntos y coincidencia con el sumario.
La interfaz se revisó con datos sintéticos a 1024×768 y 1400×960.

## Imprimir y guardar PDF

Los botones **Imprimir** y **Guardar PDF** están en la pestaña Tendencia.
Imprimir abre una vista previa con acceso al diálogo de impresión. Ambos usan
el mismo generador y una instantánea de la selección actual:

- Sólo estudios marcados en Graficar y filas de las fases PRE/POST activas.
- Tabla completa, con todos sus parámetros aunque la pantalla tenga desplazamiento.
- Los tres gráficos con los parámetros elegidos en sus selectores, sin resaltado
  de una fila ni controles de la interfaz. Los gráficos se dibujan directamente
  sobre el PDF/la impresora, conservando líneas y texto vectoriales.
- Nombre, apellido, DNI, fecha de nacimiento, sexo, período representado y número
  de estudios; no se toma el paciente ni la fecha de una maniobra abierta aparte.
- Encabezado enriquecido, logo, márgenes y tamaño de papel de Configuración →
  Informe, compartidos con el informe espirométrico. La orientación de Tendencia
  es apaisada, sin cambiar la orientación del informe de un estudio.

Con muchas filas se agregan páginas automáticamente. Se repiten el encabezado,
los datos del paciente y las cabeceras de la tabla; las filas PRE/POST de una
visita permanecen juntas. Los tres gráficos se mantienen en una misma página,
a continuación de la tabla o en una página nueva según el espacio. Cada página
incluye fecha de emisión y número de página. No se recorta una captura de pantalla.

Sin estudios seleccionados, los botones se desactivan. La exportación no altera
la selección, los puntos interactivos, los resultados ni las referencias.
Se verificaron encabezados personalizados, filtros, valores del sumario y
paginación larga en A4, Carta y Legal, con bases temporales y datos sintéticos.
