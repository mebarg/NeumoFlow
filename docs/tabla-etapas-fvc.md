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


## Revisión de calidad por parámetro

La columna **Calidad** muestra los avisos de la maniobra y la evaluación separada
de FEV1 y FVC. Por ahora no se muestra el botón de revisión manual. Se conservan
el detector, las marcas de la curva, las decisiones guardadas y la herramienta de
confirmar/descartar para una futura presentación de esa funcionalidad.

La curva seleccionada muestra el intervalo sospechoso en ambos gráficos: ámbar
si está pendiente y rojo si una revisión guardada confirmó el evento. Las
sospechas descartadas no se marcan. Los resultados medidos y muestras originales
permanecen intactos, y las decisiones existentes se conservan al exportar `.espiro`.

La evaluación de FEV1 y FVC es independiente. Una sospecha de tos durante el
primer segundo desde el T0 guardado pone FEV1 en revisión; confirmarla impide usar
ese FEV1 en los mejores valores, sin invalidar automáticamente FVC. Un cierre
glótico o interrupción confirmados afectan FVC y, si intersectan el primer
segundo, también FEV1. La falta de meseta requiere revisar FVC, sin descartar por
ese motivo FEV1. El detector no reconoce todas las alternativas de fin espiratorio.
Los índices de flujo PEF/FEF se retienen de forma conservadora cuando hay eventos
sin descartar o problemas en los parámetros de base.

Para nuevas capturas, «Incluir» selecciona la maniobra, pero solo sus parámetros
sin alertas pendientes o confirmadas aportan al compuesto, sumario e historial.
El borrador de interpretación exige al menos tres valores disponibles por cada
parámetro principal y comprueba la repetibilidad de esos valores por separado.
Se conservan las referencias y la calidad originales de Breeze. Las capturas
nativas anteriores no se reevalúan hasta abrir y guardar expresamente su revisión.

**Límites:** son reglas orientativas de ingeniería, no un detector clínicamente
validado ni una graduación ATS/ERS. «Sin alertas automáticas» requiere igualmente
revisión visual. El patrón de tos busca caída y recuperación del flujo en ventanas
de 150 ms con un umbral del mayor entre 0,5 L/s y 20 % del pico. El de cierre busca
flujo casi nulo durante 300 ms antes de que termine la parte activa; no puede
distinguir con fiabilidad todos los cierres terminales de un fin normal. No detecta
de forma fiable fugas, obstrucción de boquilla ni todos los esfuerzos submáximos.
Falta validar sensibilidad/especificidad con curvas reales etiquetadas.

Criterios de separación de parámetros: [ATS/ERS 2019, evaluación dentro de la
maniobra](https://pmc.ncbi.nlm.nih.gov/articles/PMC6794117/). Los umbrales de detección
de artefactos son propios de esta implementación y no se presentan como umbrales
validados por esa norma.


## Aviso de progreso de la sesión FVC

La franja junto a PRE/POST muestra el progreso automáticamente, sin abrir una
ventana adicional. Cuenta FEV1 y FVC por separado, únicamente entre maniobras
incluidas y valores sin alertas de los controles disponibles. PRE y POST no se
mezclan. El estado del dispositivo sigue en una etiqueta independiente.

- Al iniciar: realizar una maniobra.
- Con dos valores por parámetro repetibles: aviso ámbar, intentar un tercer valor.
- Con tres o más valores por parámetro y repetibilidad alcanzada: aviso verde,
  «Objetivo automático alcanzado». Suena una vez al alcanzarlo tras una captura.
- Con diferencias excesivas: aviso ámbar para mejorar repetibilidad.
- Con avisos de calidad: se indica repetir o revisar la curva.
- Con edad ausente o calidad original no evaluable: estado neutro, sin atribuir
  automáticamente aceptabilidad a datos importados/históricos.

La ayuda del indicador detalla los recuentos, la diferencia entre los dos mejores
FEV1 y entre las dos mejores FVC y los límites aplicados: 150 mL para mayores de
6 años; hasta 6 años, el mayor entre 100 mL y 10 % del mejor valor de cada parámetro.
Tras ocho intentos en adultos sin alcanzar el objetivo, se pide evaluar si
continuar. Nunca se detiene la prueba ni se impide guardar/imprimir por este aviso.

ATS/ERS 2019 propone tres FEV1 y tres FVC aceptables y repetibles como objetivo
(grado A). Dos mediciones aceptables repetibles pueden corresponder a grado B,
que puede ser clínicamente útil; no alcanzar A no prohíbe interpretar el estudio.
El grado se determina por separado para cada parámetro y fase.
[Norma: evaluación entre maniobras y tabla 10](https://pmc.ncbi.nlm.nih.gov/articles/PMC6794117/).

El color de NeumoFlow expresa el objetivo de los **controles automáticos
implementados**. No se presenta como una graduación ATS/ERS validada y requiere
revisión de curvas/esfuerzo. No cambia la selección de valores ni las reglas del
borrador de interpretación. La decisión de continuar o finalizar corresponde al
operador, considerando también la tolerancia del paciente.
