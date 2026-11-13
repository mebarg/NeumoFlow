# Paquete USB CPFS/D para Windows 10 x64

## Origen y alcance

`package/` contiene el INF y CAT exportados con PnPUtil del dispositivo
`USB\VID_0EE5&PID_0103` de la VM Windows 10 del mantenedor. El INF coincide
byte por byte con el original encontrado en `C:\Users\Mario\usb_driver`.
Se copiaron del mismo paquete original los coinstaladores WinUSB/WDF de x86 y
amd64 referidos por el INF. No se distribuyen los filtros, libusb0/libusbK ni los
instaladores ejecutables que también había en esa carpeta.

El INF conserva su copyright y aviso GNU LGPL de Pete Batard/libwdi.
Su plantilla y el código generador están disponibles en:
https://github.com/pbatard/libwdi/tree/v1.5.1/libwdi
Los coinstaladores son redistribuibles Microsoft procedentes del paquete original;
no se alteran sus bytes ni firmas. En Windows 10 el servicio WinUSB es del sistema.

## Firma y confianza

El CAT está firmado con el certificado autofirmado generado por libwdi:
`AE87D0D43947DE135B9C33F87D00CE9E9ED25D2B`.
Windows lo reportó `Valid` en la VM de origen. No es una certificación WHQL
ni un certificado de fabricante emitido por una autoridad pública.
`signer.cer` contiene sólo el certificado público, sin clave privada.
Caduca el **1 de enero de 2029 UTC**. La preparación y la instalación comprueban
la fecha y rechazan el paquete vencido. Renovar y volver a probar antes de esa fecha.

El instalador, elevado, incorpora ese certificado exacto a Root y TrustedPublisher,
como hace libwdi, verifica el CAT y ejecuta PnPUtil con el INF específico. No cambia
las políticas de firma, no habilita test-signing y no instala filtros genéricos.
PnPUtil valida la integridad del paquete mediante su catálogo. Si el dispositivo
está presente, se comprueba que quede activo el servicio WinUSB.
El código 259 sólo se acepta si un INF con el mismo SHA256 está registrado en
Windows y la comprobación de los dispositivos presentes no encuentra errores.
No se borra el certificado al desinstalar porque podría estar en uso por el paquete
registrado en el almacén de controladores de Windows.

## Estado de validación

La app Python y el EXE fueron probados por el mantenedor en esta VM: lectura,
maniobra y PDF. **La instalación automática en Windows limpio sigue pendiente**.
`manifest.json` deja `clean_install_verified: false`; los hashes verifican
reproducibilidad, no acreditan por sí solos la instalación ni la firma Windows.
El build normal genera un candidato para probar, no una distribución ya validada.

Antes de entregar al operador, probar en una VM limpia/snapshot independiente:

1. Instalador sin Python, Zadig ni certificado/controlador previamente instalado.
2. Instalación con dispositivo conectado y desconectado; conexión posterior.
3. Abrir app como usuario normal, cero y maniobra; PDF y reconexión USB.
4. Reinstalación/actualización conserva datos y vuelve a funcionar.
5. Cancelación/error no abre automáticamente la app ni anuncia éxito.
6. Otros dispositivos conservan su controlador.

No borrar el controlador de la única VM funcional para simular limpieza. Usar
otra VM o una instantánea recuperable. La calibración con jeringa se hará cuando
esté disponible, antes de estudios de pacientes.

## Herramientas

- `check_usb_bundle.py`: hashes, archivos e identificador único del INF.
- `setup-usb-windows.ps1 -ValidateOnly`: firma/certificado en Windows, sin instalar.
- `setup-usb-windows.ps1`: preparación USB invocada por el instalador elevado.
- Log de instalación: `C:\ProgramData\Espirometro\USB\setup-usb.log`.
- `exported/`: evidencia local de preparación; no se copia al instalador.
