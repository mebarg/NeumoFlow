# NeumoFlow para Linux Mint 21.2 Victoria x64

## Instalar y utilizar

El archivo final es `neumoflow_1.0.2_mint21_amd64.deb`. Abrirlo con doble clic
en el instalador de paquetes de Mint, pulsar **Instalar paquete** e introducir
la contraseña del administrador. También puede instalarse desde la carpeta
que lo contiene:

```bash
sudo apt install ./neumoflow_1.0.2_mint21_amd64.deb
```

El paquete incorpora la aplicación, Python y sus módulos. APT resuelve las
bibliotecas del sistema que falten; puede necesitar Internet. No hace falta
instalar Python manualmente ni usar Zadig o controladores de Windows.

Después, abrir **NeumoFlow** desde el menú de aplicaciones. Conectar el CPFS/D
USB (VID 0ee5, PID 0103); si ya estaba conectado, desconectarlo y reconectarlo.
La regla udev permite el acceso desde la sesión local activa, sin ejecutar la
aplicación como root ni dar permiso universal a todos los dispositivos USB.
Si está asignado a una máquina virtual u otra aplicación, liberarlo primero.

La base, configuración y calibración se conservan por usuario en
`~/.local/share/espirometro`, o bajo `$XDG_DATA_HOME/espirometro` si esa variable
está configurada. Las actualizaciones y la desinstalación no borran esos datos.
La primera instalación trae una calibración pendiente, nunca la del equipo de
compilación. Configurar el encabezado y calibrar en el equipo de destino.

Para desinstalar: `sudo apt remove neumoflow`.

## Generar el instalador (sólo el mantenedor)

**Construir en Mint 21.x x64 o Ubuntu 22.04 x64.** No usar CachyOS, Arch, Ubuntu
24.04 ni Mint 22 para generar el paquete destinado a Mint 21.2. Se comprueba
glibc del compilador y las versiones GLIBC requeridas por cada ELF del paquete.
Se rechazan bibliotecas que requieran una versión posterior a 2.35.

En Mint, preparar las herramientas una vez:

```bash
sudo apt update
sudo apt install python3-venv python3-pip python3-dev binutils libatomic1 libusb-1.0-0 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0
```

Extraer `NeumoFlow-Fuentes-Linux-Mint21-x64.tar.gz` y, desde su carpeta
`NeumoFlow-Linux`, ejecutar:

```bash
bash packaging/crear-instalador-linux.sh
```

También funciona desde la raíz de un checkout Git. La compilación requiere
Internet para instalar las dependencias en `.venv-linux-build` y no requiere
sudo. Usa el Python 3.10 de Mint, Qt 6.8.3 y PyInstaller. No copia el entorno
Python del desarrollador, no lee pacientes y no abre el espirómetro.

Primero corre la suite de pruebas, después genera el ejecutable y verifica
Qt, iconos, referencias, tabla CPFS y biblioteca USB mediante `--self-test`.
El archivo DEB se construye sin instalar nada en el sistema de compilación.

Salida: `dist-installer/neumoflow_1.0.2_mint21_amd64.deb`, junto con su SHA256
y un registro `.build.json`. Las versiones de dependencias y el resultado de
arranque quedan en `build/linux/`. Para recompilar la misma versión, mover el
DEB anterior a otra carpeta, o usar `--version 1.0.3`. No se sobrescribe una
entrega anterior.

## Corregir un paquete sin volver a compilar

Si ya existe `dist/linux/NeumoFlow`, se puede reutilizar ese ejecutable:

```bash
python3 packaging/build_linux.py --repackage --version 1.0.2
sudo apt install ./dist-installer/neumoflow_1.0.2_mint21_amd64.deb
```

Este modo ejecuta las pruebas de empaquetado, comprueba recursos/GLIBC y vuelve
a ejecutar el self-test del binario. No descarga dependencias ni ejecuta
PyInstaller. Mantiene el registro de dependencias de la compilación original.

La versión 1.0.1 corrige la omisión de entradas de directorio en el `data.tar`
del DEB. Esa omisión hacía fallar a dpkg al crear
`/opt/neumoflow/NeumoFlow.dpkg-new`; el error posterior de tubería rota era una
consecuencia. Los directorios se incluyen ahora con propietario root, modo 0755
y antes de sus hijos, incluidas las carpetas vacías de la distribución.
No es necesario crear carpetas a mano ni quitar pacientes para corregirlo.

La versión 1.0.2 fija el formato GNU de ambos archivos tar internos. El formato
PAX predeterminado de Python produce cabeceras `x`/`g` para nombres largos o
Unicode que dpkg no admite. El generador revisa las cabeceras físicas y la
integridad de ambos flujos xz antes de escribir el DEB. Las pruebas incluyen
rutas largas, enlaces largos y nombres Unicode: no basta con listar el tar con
Python, porque su lector oculta esas cabeceras extendidas.

Formato admitido por Debian: https://manpages.debian.org/bookworm/dpkg-dev/deb.5.en.html

Se contrastó también con el dpkg 1.21.1 de Ubuntu 22.04: una variante de prueba
con PAX reprodujo el rechazo y la variante GNU se desempaquetó correctamente
en una raíz temporal. El ensayo utilizó archivos sintéticos y propietario del
usuario para poder ejecutarse sin privilegios. Las pruebas del DEB de entrega
comprueban por separado root:root. Esto verifica el formato, no acredita aún
la instalación y ejecución del NeumoFlow real ni el acceso USB en Mint.

## Comprobación pendiente en el equipo de destino

La creación del paquete y el self-test no acreditan el funcionamiento del USB
o del escritorio real. Antes de entregar al operador, probar en Mint 21.2:

1. Instalar desde el DEB en un equipo sin el entorno Python del desarrollador.
2. Abrir desde el menú como usuario normal y comprobar textos, iconos y fuentes.
3. Conectar, poner a cero y efectuar una maniobra de prueba con el CPFS/D.
4. Guardar un PDF y comprobar el encabezado; comprobar también la impresión.
5. Actualizar y desinstalar conservando la base y la configuración del usuario.

El registro de compilación mantiene `mint_desktop_and_usb_verified: false`.
No marcar una entrega como probada hasta completar esas comprobaciones.

## Referencias de empaquetado

- https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible
- https://doc.qt.io/qt-6.8/linux-requirements.html
- https://www.freedesktop.org/software/systemd/man/latest/udev.html
