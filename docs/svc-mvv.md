# SVC y MVV

Las pestañas **FVC / SVC / MVV / Sumario** pertenecen al mismo estudio. SVC y
MVV usan el flujo firmado y el ambiente de adquisición de CPFS, con el mismo
cero digital que FVC. Cambiar entre las tres pantallas no repite el cero.
Salir del estudio libera el equipo. El botón **Flujo cero** permite repetirlo.

## Uso

1. Abrir el estudio y elegir SVC o MVV. Esperar a que termine la preparación.
2. Elegir PRE/POST y el tipo de SVC (EVC/IVC) o intervalo MVV (12/15 s).
3. Pulsar **Espacio** o **Iniciar maniobra**. Se grafica toda la captura,
   incluida la respiración preparatoria y los tramos de flujo cero.
4. En SVC, obtener respiración tranquila estable y pulsar **Comenzar esfuerzo
   lento**, después seguir la indicación EVC o IVC. En MVV, pulsar **Comenzar
   intervalo MVV** al terminar la preparación e iniciar la respiración máxima.
5. Espacio finaliza manualmente. MVV también termina automáticamente al llegar
   al intervalo marcado. La captura completa tiene un límite de 60 s.
6. Revisar la curva y las comprobaciones. Marcar **Incluir** para incorporarla
   al sumario y al PDF. El guardado no implica aceptación automática.

La marca se toma en el hilo USB y en tiempo de muestras, no en el reloj de la
interfaz. Durante la captura se bloquea el cambio de página, fase y protocolo.
Para repetir otra maniobra se conserva el stream y su cero.

## Cálculo y alcance

Motor versionado `svc-mvv-v1`, muestras continuas a 100 Hz. Las mediciones usan
el flujo calibrado y corregido por ambiente una sola vez, sin nuevos filtros
ni modificación de las mediciones FVC.

**SVC:** se mide la mayor excursión de volumen en la dirección elegida después
de la marca. EVC es espiratoria; IVC, inspiratoria. La base utiliza al menos
3 ciclos tranquilos completos: se considera estable cuando los niveles de fin
de espiración de los últimos 3 están dentro del 15% de la mediana del VT. Hay
una banda muerta de 0,02 L/s y se descartan segmentos de menos de 0,12 s o 25 mL
para evitar contar oscilaciones pequeñas. Esto es una regla de segmentación
de la aplicación, no un umbral clínico de aceptabilidad.

Con base estable se calculan IC y ERV relativos al nivel espiratorio de base;
sin ella se dejan sin informar. VT es el promedio de los últimos tres ciclos.
Se comprueba meseta de menos de 25 mL en 1 s al final del esfuerzo y se avisa
si dura más de 15 s. La detección de base estable emite un aviso sonoro y la
meseta emite dos. El operador termina la captura: no se corta automáticamente
SVC al detectar una meseta. Debe supervisar la duración y finalización del
esfuerzo, además de fugas, esfuerzo máximo y cierre glótico.

**MVV:** sólo se integra el flujo espiratorio positivo del intervalo marcado:
`MVV = volumen espirado × 60 / segundos reales`. No se suma la inspiración,
no se incluye la preparación ni se extiende artificialmente la curva. Un
intervalo menor de 12 s conserva una estimación provisional en los datos y
la ayuda de la celda, pero no un valor MVV para el sumario. Se requieren al
menos dos ciclos completos detectados. Se informa VT medio por ciclo y
frecuencia calculada entre los finales de ciclos completos. No se evalúa
automáticamente si el esfuerzo fue máximo. La prueba requiere supervisión y
puede provocar fatiga o mareo.

**Sumario:** SVC y MVV máximas entre las maniobras incluidas de cada fase;
IC promedio entre las SVC incluidas que tienen IC válida; ERV y VT de la SVC
máxima. Se muestra la cantidad de maniobras incluidas y la diferencia entre
las dos mayores. Para SVC se muestra el umbral de repetibilidad de 150 mL
(o 100 mL hasta los 6 años) o 10%, el menor. Se indica el mínimo de tres SVC o
dos MVV. Estas comprobaciones no certifican calidad ATS/ERS ni normalidad.

Se pueden elegir referencias por parámetro en Configuración → FVC:
SVC con predicho de FVC o GLI 2021 VC; IC/ERV con GLI 2021; MVV con
Polgar/Zapletal2/ITS como compatibilidad Breeze, sólo predicho y porcentaje.
GLI 2021 permite LIN/z dentro de su población y rango; la aproximación FVC→SVC
y las opciones MVV no tienen LIN/z. Ver [ecuaciones-referencia.md](ecuaciones-referencia.md). La interpretación automática sigue siendo
exclusivamente de FVC. El informe incluye los resultados de SVC/MVV y páginas
con la mejor curva incluida de cada tipo/fase; la IC de una curva puede diferir
del promedio mostrado en el sumario.

## Persistencia e intercambio

Tabla separada `respiratory_measurements`: tipo, fase, inclusión, JSON de
resultados/procesamiento/ambiente, curva completa y muestras originales. Todas
las capturas se guardan pendientes de inclusión. La migración es aditiva y
no cambia las maniobras FVC existentes.

`.espiro` versión **3** conserva SVC/MVV. Sigue leyendo versiones 1 y 2. Reemplazar
un estudio sustituye también sus SVC/MVV en la misma transacción con respaldo
previo. Las instalaciones anteriores rechazan la versión 3 en lugar de perder
estas mediciones silenciosamente. La importación **desde Breeze continúa
limitada a FVC**; el nuevo registro nativo no decodifica aún sus pruebas SVC/MVV.

## Referencias y verificación

- ATS/ERS 2019, sección VC/IC, procedimiento, estabilidad, meseta y repetibilidad:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6794117/
- ATS/ERS 2005, sección MVV, intervalo de 12–15 s:
  https://doi.org/10.1183/09031936.05.00034805

Pruebas sintéticas: EVC/IVC conocidas, base inestable, ausencia de marca,
MVV de 60 L/min, preparación excluida, intervalo incompleto, datos discontinuos,
parada USB exacta, persistencia, selección, teclado, sumario, informe e intercambio
con reemplazo y rollback. PDF de prueba revisado mediante renderizado de Poppler.
Falta la validación funcional con el espirómetro y maniobras supervisadas reales;
las pruebas sintéticas no acreditan por sí mismas validez clínica o regulatoria.
