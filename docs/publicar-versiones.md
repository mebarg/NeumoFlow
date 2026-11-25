# Publicar instaladores de NeumoFlow

El flujo [Instaladores NeumoFlow](../.github/workflows/installers.yml) genera:

- `NeumoFlowSetup-X.Y.Z.exe`: Windows 10 x64, con el paquete USB.
- `neumoflow_X.Y.Z_mint21_amd64.deb`: Linux Mint 21.2 x64 y compatibles.
- Un archivo `.sha256` para comprobar cada descarga.

## Primera puesta en marcha

Subir primero los cambios de la aplicación, los generadores y `.github/workflows/installers.yml`
al repositorio. En GitHub, **Settings → Actions → General**, permitir GitHub Actions
si estuviera desactivado. El flujo solicita permiso `contents: write` solamente en
el trabajo que publica; una política de la organización puede impedirlo.
No requiere tokens personales ni contraseñas adicionales.

Antes de publicar por primera vez, usar **Actions → Instaladores NeumoFlow → Run
workflow** sobre la rama que contiene los cambios. Indicar, por ejemplo, `v1.0.3`.
Esta ejecución compila y prueba ambos paquetes, pero **no crea una release**.
Las descargas aparecen como `installer-windows` e `installer-linux` en esa ejecución,
durante 30 días. Revisar estos paquetes en las computadoras de destino.

## Publicar una versión

Con todos los cambios de esa versión confirmados y subidos, crear una etiqueta
nueva sobre ese commit y subirla:

```bash
git tag -a v1.0.3 -m "NeumoFlow 1.0.3"
git push origin v1.0.3
```

Sustituir el número en cada entrega. El formato admitido es `vX.Y.Z`, con cada
componente entre 0 y 65535. No hace falta modificar el número predeterminado de
los scripts locales: GitHub pasa la versión de la etiqueta a ambos generadores.
Un push habitual a una rama no publica instaladores.

Cuando ambas compilaciones y pruebas terminan bien, el flujo crea la release en
**Releases**, con ambos instaladores, sus hashes y las notas generadas por GitHub.
Si ya existe una release para esa etiqueta, adjunta los archivos sin reemplazar
archivos existentes. No mover etiquetas publicadas: corregir y sacar otra versión.

## Compatibilidad y comprobaciones

Windows compila en un runner Windows 2022 con Python 3.12 x64, las dependencias
fijadas en `constraints-windows.txt` e Inno Setup 6.7.3 verificado mediante SHA256.
En el runner temporal se confía en el certificado público del paquete USB después
de comprobar sus hashes. Se usa `certutil` sobre LocalMachine del runner temporal
para evitar el aviso interactivo de CurrentUser\Root, con un límite de tres minutos.
No se instala el controlador ni se accede al espirómetro. Las pruebas muestran
el nombre de cada caso para poder identificar una demora.
El instalador resultante no tiene firma de editor del ejecutable.

Linux compila con Python 3.10 dentro de Ubuntu 22.04, sobre un runner Ubuntu 24.04.
Así se conserva la base glibc 2.35 de Mint 21.2. Se comprueban las dependencias del
binario, los recursos, el arranque del ejecutable y la extracción del `.deb` con dpkg.

Cada generador ejecuta la batería de pruebas antes de empaquetar. Ante un fallo,
consultar el trabajo rojo en **Actions**; no se publica automáticamente una entrega
con una sola plataforma. La publicación vuelve a comprobar los hashes y acepta
únicamente los cuatro archivos esperados. No se incluyen bases de pacientes ni
materiales de investigación. Estas comprobaciones no sustituyen la prueba del
USB y de una instalación limpia en los equipos reales.
