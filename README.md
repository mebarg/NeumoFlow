# NeumoFlow

Aplicación de escritorio en Python y PySide6 para espirometría con CPFS/D USB.

Incluye mediciones FVC, SVC y MVV, estudios PRE/POST, historial y tendencias,
referencias configurables por parámetro, informes PDF e importación de estudios
BreezeSuite `.cow`. Los estudios propios se intercambian mediante `.espiro`.

La interfaz se adapta a pantallas de 1366×768, con desplazamiento en el sumario,
la configuración y las tendencias cuando falta altura. En los gráficos de
z-score, PRE usa círculos rellenos y POST círculos de contorno, también al imprimir.

Las capturas FVC incluyen una [revisión orientativa de calidad por parámetro](docs/tabla-etapas-fvc.md#revisión-de-calidad-por-parámetro),
con tramos sospechosos marcados y decisiones de confirmar/descartar guardadas por el operador.

## Ejecutar desde las fuentes

Crear un entorno con Python compatible con las dependencias (Python 3.12 de
64 bits es la versión utilizada para el empaquetado Windows):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app.main
```

Para probar una ventana sin maximizar: `python -m app.main --window-size 1366x768`.
El tamaño corresponde al área interior de la aplicación. Para simular el espacio
útil de un monitor de 1366×768 dejando lugar al marco y la barra de tareas, usar
`python -m app.main --window-size 1366x690`.

En Windows, consultar [las instrucciones de empaquetado](packaging/README.md).
El instalador Windows incluye la preparación del dispositivo USB; su prueba en
una instalación limpia sigue pendiente según la documentación del paquete.
Para Linux Mint 21.2 Victoria x64, consultar [el generador de paquetes DEB](packaging/linux/README.md).
La compilación debe realizarse en Mint 21.x o Ubuntu 22.04; las pruebas del
instalador con escritorio y USB en Mint siguen pendientes.

## Datos y calibración

La base de pacientes y la configuración se guardan fuera del código:

- Linux: `${XDG_DATA_HOME:-~/.local/share}/espirometro`.
- Windows: `%LOCALAPPDATA%\Espirometro`.

La calibración incluida es neutra, con fecha «pendiente». Cada equipo necesita
su calibración con jeringa y los datos ambientales antes de efectuar estudios.
Este repositorio no contiene bases de pacientes, exportaciones clínicas,
capturas USB ni calibraciones del equipo de desarrollo.

## Pruebas

Desde la raíz del proyecto, con las dependencias instaladas:

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -q
```

Las pruebas de referencia y de señal incluyen tablas de comparación y señales
de banco sin datos filiatorios. Las pruebas de software no equivalen a una
validación clínica o regulatoria del equipo.

## Documentación

- [Ecuaciones de referencia](docs/ecuaciones-referencia.md).
- [Importación y exportación](docs/importacion-estudios.md).
- [SVC y MVV](docs/svc-mvv.md).
- [Tabla FVC](docs/tabla-etapas-fvc.md).
- [Historial y tendencias](docs/tendencia-paciente.md).
- [Instalador Windows](packaging/README.md).
- [Publicación automática de instaladores en GitHub](docs/publicar-versiones.md).

## Recursos de terceros

Las tablas GLI conservan su [aviso de atribución y licencia](app/data/GLI-NOTICE.txt).
El paquete USB conserva su [documentación y procedencia](packaging/windows-usb/README.md).
Las dependencias conservan sus respectivas licencias.

`app/data/lup1.cfg` es la tabla de forma procedente de una instalación de
BreezeSuite, mantenida para el procesamiento CPFS actual. Su inclusión no
constituye una afirmación de que se haya obtenido autorización para
redistribuirla. No se incluye código fuente original ni ejecutables de Breeze.

Este repositorio contiene la aplicación y los archivos necesarios para
mantenerla y empaquetarla. Los materiales de investigación y el historial del
repositorio de trabajo se conservan por separado.
