# Importar y exportar estudios

En **Configuración → Importar / exportar** hay dos acciones:

- **Importar estudios desde una carpeta:** lee los archivos `.cow` y `.espiro` de esa carpeta, sin recorrer subcarpetas. Muestra paciente, DNI/ID, fecha, cantidad de maniobras, origen, archivo y duplicados. Permite elegir filas. Los errores de archivos individuales aparecen en los detalles sin impedir revisar los demás.
- **Exportar estudios (.espiro):** permite seleccionar estudios de la base y guardarlos juntos. Para trasladarlos, llevar el archivo a otra instalación y elegir su carpeta desde Importar.

Los duplicados existentes se muestran desmarcados. Sin activar **Reemplazar los estudios duplicados seleccionados**, se omiten aunque se marque su fila. Activar la opción no selecciona filas automáticamente. La coincidencia se vuelve a comprobar al guardar, dentro de una transacción. Se compara el identificador estable del estudio y, como alternativa, paciente más fecha/hora exacta.

Reemplazar sustituye las maniobras y el informe del estudio duplicado. No sobreescribe la ficha personal de un paciente existente. Antes del primer reemplazo se crea una copia SQLite completa en `backups/antes-importar-<fecha>.sqlite3`, junto a la base de datos. Los archivos de origen permanecen intactos. Si falla una escritura, la transacción completa se revierte.

## Lotes grandes y avance

La lectura muestra una barra, el número de archivos procesados y el archivo
actual. La preparación de la tabla y la importación tienen sus propios
contadores. La tabla se completa en tandas para mantener la interfaz disponible.
Las actualizaciones del trabajador se limitan a unas diez por segundo.

La vista previa guarda las curvas y el COW original en un directorio temporal
privado; conserva en memoria los datos de las filas, sin acumular todas las
curvas. Necesita espacio libre en el disco temporal. La lectura usa una sola
conexión a SQLite y las búsquedas por paciente/fecha tienen un índice. No hay un
límite de 10.000 archivos por carpeta: ese límite corresponde a cada paquete
`.espiro`, no a un lote de archivos COW.

**Cancelar operación** interrumpe la lectura entre archivos o estudios. Durante
la importación revierte la transacción completa; no deja un lote parcialmente
guardado. El archivo o estudio que se está procesando debe terminar antes de
atender la cancelación. Los errores individuales siguen apareciendo en los
detalles; se muestran hasta 200 observaciones para mantener la vista ágil.

Las pruebas incluyen una carpeta de 14.000 archivos con lector sintético, una
tabla de 14.000 estudios y la reversión de escrituras al cancelar. Esto verifica
el manejo de lotes; el tiempo real depende del tamaño de los COW, el disco y el
equipo.

## Breeze

Se admiten los perfiles comprobados de COW 510: exportación en formato 6.2 y exportación cifrada 6.4.1. El productor puede indicar 6.4.1 en ambos casos. El descifrador de interoperabilidad está incluido en Python y no requiere OpenSSL, instalaciones ni configuración adicional en Windows. Se validó con vectores de RFC 2268, un COW sintético cifrado independientemente con OpenSSL y los 21 estudios proporcionados (19 pares de formato y dos visitas de jeringa).

Se importan las maniobras FVC reales (EffortTypeID=0) de etapas 1/PRE y 3/POST. Las etapas que no correspondan a PRE/POST generan un error explícito para esa visita; no se convierten silenciosamente. Los registros predichos/compuestos no se convierten en maniobras adicionales. Una visita sin maniobras FVC reales se muestra como no importable. Otras modalidades no se incorporan como estudios de nuestra app.

Se preservan las fechas, informes, condiciones ambientales, referencia histórica de calibración, indicador de jeringa, valores originales, códigos ATS y las ramas inspiratoria/espiratoria. FEV1/FVC se convierte de porcentaje a razón y el pico se toma de FEFMax en L/s, no del PEF de Breeze en L/min. No se recalculan mediciones ni se vuelve a aplicar BTPS. Las curvas originales y el COW completo quedan conservados en la procedencia del estudio, además de la curva preparada para visualizar.

Las casillas de inclusión reflejan EffortSelected. Todas las maniobras reales se guardan, aunque Breeze no las haya seleccionado: en ese caso aparecen inicialmente sin incluir en el sumario y se pueden seleccionar desde la pantalla de medición. Se informa esto en la vista previa. El sumario de la aplicación se arma con las maniobras incluidas, no se copia como una segunda maniobra el compuesto de Breeze.

Los predichos recuperados se usan como **Breeze original**, sin reemplazarlos por GLI. Los z-scores se calculan como **(medido − predicho) / desviación estándar**, usando los registros originales Predicted (tipo 1) y StandardDeviation (tipo 5). El cociente FEV1/FVC y su desviación se convierten juntos de porcentaje a razón. Se muestran en medición, sumario e informe, indicando su procedencia. Si falta una desviación positiva válida, hay registros de referencia ambiguos o es un estudio de jeringa, se muestra «–». Los estudios ya importados recuperan la desviación del COW conservado, comprobando su hash y correspondencia, sin reimportar ni modificar mediciones. El formato `.espiro` conserva estas referencias. No se infieren límites normales históricos ni calidad ATS/ERS moderna. Los códigos de catálogo de sexo y etnia se conservan en la procedencia, pero quedan sin asignar en fichas nuevas hasta revisión manual. En fichas existentes se mantienen sus datos personales. La configuración y la calibración activa del equipo no se modifican al importar.

## Formato propio, versión 3 (lectura compatible con versiones 1 y 2)

`.espiro` es un ZIP comprimido que contiene:

- `manifest.json`: identificador `espirometro.studies`, versión entera 3, fecha de exportación y lista de archivos con SHA-256.
- `studies/000001.json`, etc.: objetos UTF-8 con `patient`, `session` y `maneuvers`.

La versión 2 incorporó la selección de ecuaciones por parámetro. La versión 3 añade la lista `respiratory` con las mediciones SVC/MVV, sus curvas, muestras y estados de inclusión. Se siguen leyendo paquetes de versiones 1 y 2. Las instalaciones antiguas rechazan la nueva versión para evitar pérdida silenciosa de mediciones.

Incluye los datos del paciente, identificadores estables, antropometría de cada visita, informe, estados de inclusión/impresión, fases, resultados exactos, muestras, parámetros de procesamiento y curvas. Si el origen era Breeze, también conserva su procedencia y archivo original. No usa pickle, ejecutables ni rutas de extracción. Los paquetes contienen datos personales y **no están cifrados**.

La lectura comprueba versión, campos, hashes, fechas, estados, números finitos y curvas; rechaza nombres repetidos, estudios repetidos, archivos no declarados y versiones desconocidas. Límites: hasta 10.000 estudios, 128 MiB por entrada y 512 MiB descomprimidos en total. La exportación se escribe en un archivo temporal, se verifica y se publica mediante reemplazo atómico. No exporta configuración local, logos del informe ni la calibración activa del equipo; para eso se necesita un respaldo completo de la instalación.

## Validación

Las pruebas sintéticas cubren intercambio entre dos bases temporales, precisión de valores y curvas, omisión/reemplazo con copia de seguridad, conflictos de identidad, reversión ante error, archivos dañados y estados de la vista previa. No requieren equipo USB ni incluyen datos personales reales.

```
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -q
```

La distribución Windows incorpora estos módulos automáticamente con el empaquetado existente; hay que reconstruir el ejecutable/instalador para llevar este cambio a otra computadora.

Referencia del decodificador legado: [RFC 2268, RC2](https://www.rfc-editor.org/rfc/rfc2268). El formato propio no usa RC2.

## Presentación volumen-tiempo FVC

Los puntos exportados por Breeze pueden conservar un reloj de adquisición con
inicio distinto de cero, y el registro combinado puede contener inspiración
antes o después de la espiración. Por eso no se usa directamente `acq_curve`
como superposición final de volumen-tiempo.

`app/fvc_display.py` prepara una vista de la rama original
`FVLExpiratorySourceData`, tanto para los estudios ya importados como para los
nuevos. Se conserva la rama completa para flujo-volumen y no se escribe la
transformación en la base de datos ni en los COW originales.

Cuando están presentes y son consistentes, se recupera el origen de tiempo
exportado mediante dos expresiones independientes:

- `último tiempo espiratorio − ExpTime`;
- `tiempo del punto de flujo máximo − ToFEFMax`.

Sólo se usa ese origen si ambos coinciden dentro de 0,005 s (resolución del
canal temporal comprobado, escala 200) y queda dentro de la rama. Se traslada
el tiempo a ese origen y el volumen a la base del tramo espiratorio. Si el
origen cae entre dos puntos, se interpola únicamente ese segmento de dibujo
para iniciar la vista en t=0, manteniendo los puntos posteriores originales.
El volumen en t=0 puede ser positivo: no se fuerza a cero ni se redefine BEV.
No se integra el flujo, no se recalcula un tiempo cero ATS, ni se modifican
FVC, FEV1, cocientes, duración, predichos o BTPS.

Si faltan esos tiempos o no son consistentes, sólo se traslada el primer punto
espiratorio a t=0 y volumen=0; no se supone un origen clínico más preciso. Si
falta la rama espiratoria original o es ilegible, no se sustituye por el ciclo
inspiratorio completo como si fuera una espiración comparable.

La misma vista se usa al revisar FVC, en el Sumario y en sus gráficos del PDF.
Las nuevas capturas nativas usan su `vol_curve` espiratoria ya calculada; los
registros nativos antiguos que sólo conservan `acq_curve` tienen una traslación
simple de origen. La captura en vivo conserva la señal completa y muestra la
preparación o el flujo cero desde el comienzo. SVC, MVV y calibración conservan
sus curvas completas y su escala temporal propia.

Las pruebas cubren desfases temporales, rama espiratoria independiente,
recuperación consistente del origen, metadatos incompletos, conservación de
los blobs y resultados guardados, colores y selección, Sumario y captura en vivo.
