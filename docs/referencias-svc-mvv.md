# Investigación de predichos SVC/MVV — 12/11/2026

Investigación bibliográfica y lectura del catálogo recuperado; no modifica la
configuración ni los cálculos de la aplicación.

## SVC: usar el predicho de FVC

Hall et al., GLI 2021 para volúmenes estáticos, describe expresamente que muchos
laboratorios utilizan el predicho de FVC para FVC y VC. También publica
referencias separadas de VC, IC y ERV. Por tanto, usar FVC como referencia
comparativa para SVC es una práctica documentada; no debe confundirse con una
ecuación desarrollada específicamente para VC. La similitud de las referencias
no demuestra equivalencia individual de sus límites o z-scores.

GLI 2021 se limita a 5–80 años y se derivó de personas de ascendencia europea.
Su aplicación debe considerar la población atendida. No es GLI Global 2022.

Fuente primaria:
Hall GL et al. Official ERS technical standard: Global Lung Function Initiative
reference values for static lung volumes in individuals of European ancestry.
Eur Respir J. 2021;57:2000289.
https://doi.org/10.1183/13993003.00289-2020
https://publications.ersnet.org/lookup/doi/10.1183/13993003.00289-2020
La fuente se consultó mediante los extractos indexados del editor; la apertura
directa devolvió 403. La calculadora oficial confirma VC, IC y ERV:
https://gli-calculator.ersnet.org/

El respaldo recuperado de Breeze tiene expresiones propias de SVC
(`ParamsDefID=52`, VCSVC), IC (53) y ERV (54). No hay fila seleccionada para 52
en PredSelectedAuthors. Esto es compatible con que la instalación derive su
referencia activa de FVC, como informa el usuario, pero por sí solo NO prueba
el enlace ejecutado por Breeze. No se desensambló ese enlace en esta revisión.

## MVV: catálogo de la instalación Breeze

La selección del parámetro 48/MVV coincide con la captura para ambos sexos:
Polgar en pediatría, Zapletal2 en adolescencia e ITS en adultos. Las categorías
de la interfaz no establecen por sí solas los límites de edad bibliográficos.

Expresiones del catálogo, con H en centímetros, h en pulgadas y A en años:

| Autor | Predicho MVV (L/min) | Registro auxiliar tipo 1 |
|---|---|---|
| Polgar | `1.276 H − 99.5`, ambos sexos | `21` |
| Zapletal2 | `10^(−1.9178 + 3.0388 log10(H))/1000`, ambos sexos | `0.1141` |
| ITS masculino | `3.39 h − 1.26 A − 21.4` | `29` |
| ITS femenino | `2.05 h − 0.57 A − 5.5` | `10.7` |

Estos son datos de implementación de la instalación, no una nueva
transcripción validada directamente contra las tablas bibliográficas originales.
No redondear los coeficientes de ITS al convertir pulgadas a centímetros.

Polgar corresponde a la familia bibliográfica Polgar/Promadhat, Pulmonary
Function Testing in Children: Techniques and Standards (1971); Zapletal2
concuerda con la expresión reproducida como Zapletal/Šamánek/Paul, Lung Function
in Children and Adolescents (1987), en manuales de equipos. El editor confirma la obra de Zapletal (1987):
https://karger.com/books/book/1808/Lung-Function-in-Children-and-AdolescentsMethods
No se pudo inspeccionar la tabla original de esos libros. La identidad exacta de ITS con Kory/Lindall,
sus rangos y su compilación siguen pendientes de confirmación primaria.

El manual Office Medic, publicado por QRS, reproduce la fórmula de Zapletal:
https://www.maxlifelive.com/_files/ugd/e1617b_00c3909dd4aa4272ba825162920dc2c3.pdf
Es una reproducción del fabricante, no el libro original.

**No convertir automáticamente los registros auxiliares de Zapletal2 en una DE
lineal de L/min.** La expresión es logarítmica y el valor 0.1141 exige comprobar
la escala del error y el algoritmo original antes de producir LIN/z-score.
Encontrar un número de dispersión no valida por sí mismo esa operación.

Extracción reproducible, sin datos de pacientes:
`base_breeze/catalogo-30166-5784/analisis/referencias-svc-mvv.json`.
Incluye autores resueltos, expresiones y hashes de procedencia; los originales
no se modificaron.

## Alternativas bibliográficas MVV

- Neder JA et al. Reference values for lung function tests: II. Maximal
  respiratory pressures and voluntary ventilation. Braz J Med Biol Res.
  1999;32:719–727. https://doi.org/10.1590/S0100-879X1999000600007
  Candidato adulto para revisión adicional. El acceso directo al texto en SciELO
  estuvo bloqueado; no se validan aquí los coeficientes por transcripciones OCR.
- Silva JC et al. (2020). Reference equation for maximal voluntary ventilation in
  children and adolescents. https://pubmed.ncbi.nlm.nih.gov/31742910/
  doi:10.1002/ppul.24576.
  Estudio primario de 348 voluntarios de 6–17 años; 248 para desarrollo y 100
  para validación. Incluye FEV1 y PEF, por lo que exige revisar el uso previsto
  antes de tratarlo como referencia poblacional independiente de la espirometría.
- Otto-Yáñez M et al. Front Physiol. 2020;11:537.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7296050/
  La MVV estimada multiplicando el FEV1 medido no es intercambiable con la MVV
  medida; debe mantenerse diferenciada de un predicho poblacional.

## Propuesta para la aplicación

- SVC: selector explícito «Referencia de FVC» como opción de continuidad con
  Breeze, identificando que es una referencia de FVC aplicada a SVC.
- Ofrecer también GLI 2021 VC y, para IC/ERV, sus ecuaciones específicas,
  respetando sus límites de población y edad.
- MVV: opciones de compatibilidad Polgar, Zapletal2 e ITS cuando se confirmen
  los rangos y la estadística; revisar Neder como alternativa para adultos.
- Predicho y % del predicho pueden incorporarse antes que LIN/z-score si la
  dispersión de una ecuación aún no está verificada. No asignar z=0 por defecto
  ni inventar una DE como porcentaje fijo del predicho.
- No cambiar retrospectivamente referencias de estudios guardados ni confundir
  MVV medida, MVV estimada por FEV1 y MVV predicha por edad/talla/sexo.

## Estado implementado

Se incorporaron los selectores en Configuración → FVC por parámetro.
GLI 2021 VC/IC/ERV tiene motor LMS contrastado numéricamente; SVC con predicho
FVC y MVV con el catálogo Breeze sólo informan predicho y porcentaje.
Los límites conservadores de Polgar/Zapletal y la falta de límite superior
confirmado para ITS se explicitan en la configuración; ITS no se activa por
defecto y no produce LIN/z. No se considera verificada la estadística auxiliar
del catálogo. Ver [ecuaciones-referencia.md](ecuaciones-referencia.md) y
[gli-volumes-sources.md](gli-volumes-sources.md).
