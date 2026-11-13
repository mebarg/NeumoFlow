# GLI 2021: VC, IC y ERV

Modelo de Hall GL, Filipow N, Ruppel G, et al. *Official ERS technical standard:
Global Lung Function Initiative reference values for static lung volumes in
individuals of European ancestry*. ERJ 2021;57:2000289.
https://doi.org/10.1183/13993003.00289-2020

Se implementan VC (aplicada a SVC), IC y ERV, de 5 a 80 años, ambos sexos.
Se requiere ascendencia europea explícita (`caucasian` en la ficha actual).
No se infiere de nacionalidad y no se extrapola a otras poblaciones/edades.
Es un modelo distinto de GLI Global 2022 para espirometría forzada.

## Procedencia reproducible

Coeficientes y tablas transcritos de **pft 1.0.4**, commit
`7489d487bb5bffd5418e66362ebeb0a7332c9916`, licencia MIT incluida en
`app/data/GLI-NOTICE.txt`:

- https://github.com/overdodactyl/pft/tree/7489d487bb5bffd5418e66362ebeb0a7332c9916/R
- https://github.com/overdodactyl/pft/tree/7489d487bb5bffd5418e66362ebeb0a7332c9916/data-raw
- Fuente numérica: `data-raw/splines_lung.RData`.
- Git blob SHA1: `ad461626d8090d9d3896f84bc0faf60dc01280e2`.
- SHA256: `9acca95c978310a6b90000719ba3d6822c47ecf6390f10666864835c5712dde5`.

Desde la raíz del repositorio, `python tools/build_gli_volumes_data.py /ruta/splines_lung.RData`
reproduce `app/data/gli_volumes_2021.json`. Es un extractor restringido al archivo
con ese hash: verifica las 56 columnas numéricas de 301 edades y conserva las
seis tablas VC/IC/ERV por sexo. No es un lector R genérico. El orden de tablas
coincide con `data-raw/build_gli_2021_volumes.R`. No se ejecuta R ni se descarga
nada durante el uso de la aplicación.

Se interpola Mspline linealmente en la grilla de 0,25 años. Para estos seis
modelos, S y L no necesitan splines:

- `M = exp(a + b*edad + c*ln(talla_cm) + Mspline)`.
- `S = exp(d + e*edad)`; `L` constante, con coeficientes por sexo/parámetro.
- `z = ((medido/M)^L - 1)/(L*S)`.
- `LIN = M*(1 - 1,645*L*S)^(1/L)`.

## Contraste numérico

`tests/fixtures/gli_volumes_2021_oracle.csv` contiene 147 combinaciones únicas
de sexo, edad y talla tomadas de `data-raw/gli_test_grid_GLI.csv` del mismo
commit. Ese conjunto conserva salidas de la calculadora web GLI, independientes
de nuestro motor. Se seleccionaron edades 5–80 y tallas 100–195 cm, sin imponer
esas tallas como nuevos límites del modelo. Para VC/IC/ERV se comparan predicho
y LIN a tres decimales (tolerancia 0,000501 L).

Además se contrastan ocho ejemplos VC de la tabla suplementaria S4 del artículo,
las identidades z=0 en el predicho y z=−1,645 en el LIN, la interpolación y los
límites de población/edad. Esto verifica la implementación numérica y no
constituye validación clínica ni regulatoria del equipo.
