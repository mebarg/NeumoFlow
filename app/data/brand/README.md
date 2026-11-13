# Icono NeumoFlow

`neumoflow-source.png`: imagen original del usuario, sin modificar.
`neumoflow-transparent.png`: recorte con alfa realizado con la herramienta integrada image_gen.
`neumoflow.png` y `neumoflow.ico`: recursos de la app derivados del recorte mediante `tools/build_brand_assets.py`.
El ICO contiene tamaños 16, 24, 32, 48, 64, 128 y 256.

## Prompt final del recorte

Precisely remove the black corners from this supplied app icon. Treat it as a mask operation, not a redraw: make only the nearly pure BLACK exterior region connected to the four image corners transparent. Keep all teal pixels completely opaque, even dark teal; do not make any part inside the rounded teal tile transparent. Invariant: preserve the original image RGB inside the tile exactly, including white lungs, turquoise flow curve and teal background. Smooth alpha at the outer teal boundary. No color changes, no interior holes, no new dark patches. Output RGBA with genuinely transparent corners.

Se usó el modo integrado con `transparent_background=true`; no se utilizó CLI ni API externa propia.
Se verificaron visualmente la barra lateral y, mediante una prueba automatizada,
las cuatro esquinas transparentes del PNG y de los siete tamaños del ICO.
La imagen original RGB se conserva para futuras revisiones.
