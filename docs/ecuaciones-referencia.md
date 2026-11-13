# Ecuaciones de referencia por parámetro

En **Configuración → FVC → Ecuaciones de referencia por parámetro** se elige
una ecuación para FVC, FEV1, FEV1/FVC, FEF25–75, SVC, IC, ERV y MVV de forma independiente. PEF
se incluye como «Sin referencia»: todavía no tiene una ecuación implementada.
Cada selector sólo ofrece opciones compatibles con su parámetro.

- **GLI Global 2022**, sin etnia: FVC, FEV1 y FEV1/FVC, de 3 a 95 años.
- **GLI-2012**, implementación existente de pyspiro: FVC, FEV1, FEV1/FVC y
  FEF25–75; necesita la etnia de la ficha. Se conserva su comportamiento.
- **Sin referencia**: se muestra la medición, con «–» en los campos de referencia.

El botón **GLI Global + GLI-2012 para FEF25–75** configura la combinación.
El botón **GLI-2012** restaura la selección anterior de la aplicación. Al
actualizar una instalación se mantiene GLI-2012 como selección inicial;
la nueva combinación se activa explícitamente. No hay sustituciones automáticas
si faltan datos o una ecuación no admite el parámetro/edad.

Los cambios se guardan automáticamente y afectan a estudios creados después.
Cada nuevo estudio conserva una política de referencia versión 2 en
`source_json.reference_policy`, con el identificador de implementación por
parámetro y la etnia usada por GLI-2012. Configuración posterior y edición de
la etnia del paciente no cambian esa selección guardada. Estudios previos sin
política siguen usando GLI-2012, y los de Breeze mantienen sus referencias
exportadas. No se recalculan mediciones ni BTPS.

La política se conserva al exportar/importar `.espiro`, en paquetes versión 3, que impiden que aplicaciones anteriores ignoren las
ecuaciones elegidas. Se mantiene la lectura de paquetes versiones 1 y 2. Se rechazan políticas desconocidas o combinaciones no admitidas.
El sumario, las ayudas de medición, el PDF y la interpretación identifican las
referencias por parámetro. Predicho, porcentaje, LIN y z-score de cada parámetro
proceden siempre de la misma ecuación, sin mezclar sus componentes.

## Implementación GLI Global

Modelo LMS de Bowerman et al., doi:10.1164/rccm.202205-0963OC. Coeficientes
numéricos y splines del libro `gli_global_lookuptables_dec6.xlsx`, obtenidos
mediante la transcripción CSV reproducible de **pft 1.0.4**, commit
`7489d487bb5bffd5418e66362ebeb0a7332c9916`. Fuentes y hashes de cada CSV en
[gli-global-sources.json](gli-global-sources.json); atribución y licencia en
`app/data/GLI-NOTICE.txt`. El motor propio usa sólo la biblioteca estándar de
Python, funciona sin Internet y se empaqueta para Windows.

Se interpolan linealmente los splines entre filas de 0,25 años. No se extrapola
fuera de 3–95 años. La talla se utiliza en centímetros y el cociente como razón
(0–1, no porcentaje). Se calcula:

- `M = exp(a0 + a1 log(talla_cm) + a2 log(edad) + Mspline)`.
- `S = exp(p0 + p1 log(edad) + Sspline)`.
- `L = q0 + q1 log(edad)`.
- `z = ((medido/M)^L − 1)/(L S)`.
- `LIN = M (1 − 1,645 L S)^(1/L)`.

Se contemplan los límites matemáticos para L=0 y se comprueba el dominio.
No hay referencias GLI Global para FEF25–75 ni PEF en este motor.

## Validación

`tests/fixtures/gli_2022_oracle.csv` procede de pft: fue generado con **rspiro**,
una implementación independiente. Comprueba 30 combinaciones de sexo, edades
10/25/45/65/85 y tallas 155/170/185, con FVC, FEV1 y cociente medidos al 85%
del predicho. Predicho, LIN, z y porcentaje coinciden con tolerancia de 10
decimales. No equivale a una validación clínica o regulatoria del equipo.
Se prueban también límites de edad, interpolación, parámetros no disponibles,
selección mixta, persistencia, exportación/importación y visualización del informe.

Fuentes oficiales:
- https://gli-calculator.ersnet.org/
- https://www.ersnet.org/science-and-research/ongoing-clinical-research-collaborations/the-global-lung-function-initiative/gli-resources/
- https://doi.org/10.1164/rccm.202205-0963OC

## SVC y MVV

Los selectores adicionales empiezan en **Sin referencia** para conservar la
configuración existente; se activan explícitamente y sólo para estudios nuevos.
Las políticas versión 1 se leen con los cuatro parámetros adicionales desactivados,
sin reescribir su JSON histórico. Los botones de combinación FVC no cambian SVC/MVV.

- **SVC → Referencia de FVC**: usa la ecuación FVC guardada en ese estudio
  (incluida la opción sin referencia). Informa predicho y porcentaje. No traslada
  el LIN ni z-score de FVC a SVC.
- **SVC / IC / ERV → GLI 2021 volúmenes**: modelo específico VC/IC/ERV,
  5–80 años y ascendencia europea declarada. Predicho, %, LIN y z-score.
  [Procedencia y validación numérica](gli-volumes-sources.md).
- **MVV → Polgar / Zapletal2 / ITS (Breeze)**: compatibilidad con las expresiones
  del catálogo recuperado. Sólo predicho y porcentaje; sin LIN/z-score ni
  clasificación de anormalidad por esos modelos. Polgar 7–17 años;
  Zapletal2 6–18 años y talla 107–182 cm; ITS adulto desde 18 años, con límite
  superior de edad aún no confirmado. La opción ITS se identifica como
  compatibilidad y requiere criterio del operador, no se activa por defecto.
  [Coeficientes, fuentes y límites pendientes](referencias-svc-mvv.md).

No hay sustituciones de modelo automáticas. Un estudio de jeringa sin BTPS no
recibe referencias SVC/MVV. Las curvas y magnitudes medidas no se modifican.
Las tablas de SVC/MVV muestran predicho, porcentaje y z del parámetro principal;
IC/ERV tienen ayudas por celda y sus columnas completas en el sumario y PDF.
El rojo por valores bajo el LIN sólo se aplica cuando la referencia tiene LIN
verificado; no se inventan límites para MVV ni para la aproximación FVC→SVC.
