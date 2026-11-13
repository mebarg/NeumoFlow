# Instalador Windows 10 x64

La entrega final al operador será un solo EXE: instalar, aceptar el permiso de
Windows, conectar el espirómetro y abrir el acceso directo. No necesita Python,
Zadig ni seleccionar controladores. Los componentes van incluidos para instalar
sin Internet.

## Estado

La app Python y el ejecutable funcionan en la VM Windows 10 del mantenedor.
El instalador integra ahora el paquete WinUSB exportado de esa VM, con su
certificado público y coinstaladores originales. **Falta probar el instalador,
especialmente en Windows sin controlador/certificado previo.** La compilación
produce un candidato para esas pruebas; no se considera validado para entrega.
Detalles de firma, procedencia y pruebas: `windows-usb/README.md`.

## Preparación del mantenedor

Windows 10 x64 1809 o posterior, Python 3.12 x64 con lanzador `py`, e Inno Setup 6.
Requiere Internet para descargar dependencias al construir.

1. Cerrar la aplicación.
2. Ejecutar `packaging\crear-instalador.cmd` en Windows.
3. El script comprueba hashes y firma USB, ejecuta pruebas, empaqueta con
   PyInstaller, comprueba recursos/DLL del EXE y compila Inno Setup.
4. Salida: `dist-installer\EspirometroSetup-1.0.0.exe`.
5. Copiar ese EXE a Windows para probar la instalación completa.

La primera vez se crea `.venv-win`. El paquete `libusb-package` usa el wheel
Windows precompilado; no se acepta una compilación sin DLL.
Las versiones usadas quedan registradas en `build\windows-packages.txt`.
La comprobación del ejecutable queda en `build\windows-self-test.json` y no
abre USB ni la base de pacientes.

Para probar sólo el ejecutable, en un Windows que ya tiene WinUSB:
`packaging\crear-ejecutable-prueba.cmd`. Genera `dist\Espirometro\Espirometro.exe`;
conservar toda esa carpeta junto al EXE. No configura el controlador.
Para ejecutar fuentes: `packaging\probar-app-windows.cmd`.

## Instalación USB

Sólo se asocia `USB\VID_0EE5&PID_0103` a WinUSB. El instalador registra el
certificado público autofirmado de ese paquete en los almacenes Root y
TrustedPublisher de Windows, comprueba su identidad/vigencia y la firma del CAT,
y usa PnPUtil. No incluye claves privadas ni cambia políticas de firma/arranque.
El certificado caduca el 1 de enero de 2029 UTC; renovar el paquete antes.
Si hay un fallo no se abre la app. Log: `%ProgramData%\Espirometro\USB\setup-usb.log`.
Si Windows pide reinicio se informa mediante el instalador.
La app se abre como usuario normal después de la instalación elevada.

## Datos

La base, calibración y ajustes se guardan por usuario en
`%LOCALAPPDATA%\Espirometro`; la base es `espirometro.sqlite3`.
Una actualización o desinstalación no borra esos datos.
El paquete incluye una calibración neutra pendiente, no pacientes ni la
calibración histórica del equipo de preparación. Calibrar con jeringa y
configurar encabezado/logo en la computadora de destino. La migración de datos
existentes se hace por separado.

## Fuentes

`python3 packaging/prepare_windows_source.py` crea
`dist-installer/Espirometro-Fuentes-Windows-x64.zip` con lista explícita de código,
recursos y paquete USB. No incluye DB, informes, capturas ni entornos virtuales.
Es para el mantenedor, no es el instalador que se entrega al operador.

## Referencias

- https://pyinstaller.org/en/stable/
- https://github.com/libusb/libusb/wiki/Windows
- https://github.com/pbatard/libwdi/wiki/Zadig
- https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/pnputil-command-syntax
- https://doc.qt.io/qt-6.11/supported-platforms.html
