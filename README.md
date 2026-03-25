# La Salle - Centro de Diagnóstico Automático (NetTest)

Este programa es una herramienta integral de diagnóstico de red diseñada para el personal de IT de La Salle. Permite realizar pruebas automáticas en las diferentes capas del modelo OSI, asegurando que la conectividad a Internet y a los servicios internos sea óptima.

## Características Principales

- **Diagnóstico Capa 1 (Física):** Detecta el estado del enlace de red.
- **Diagnóstico Capa 2 (Enlace):** Verifica la asignación de IP via DHCP y permite la configuración manual si el servicio falla.
- **Diagnóstico Capa 3 (Red):** Pruebas de conectividad local (Gateway) y externa (Internet/ICMP).
- **Diagnóstico de Aplicación:** Resolución DNS y simulacro de navegación HTTP(S) hacia dominios específicos.
- **Gestión Wi-Fi:** Escaneo de redes, conexión y olvido de perfiles.
- **Prevención de Conflictos:** Verifica si una IP manual ya está en uso antes de aplicarla.

## Requisitos de Instalación

Para ejecutar el script directamente desde Python, necesitarás:

1. **Python 3.10+**
2. Instalar las dependencias listadas en `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Instrucciones para Generar el Ejecutable (.exe)

Para distribuir esta herramienta como un archivo ejecutable único en Windows, utiliza `PyInstaller`. 

### Preparación

Asegúrate de tener los siguientes archivos en el mismo directorio que `net_test.py`:
- `icon.ico` (Icono de la aplicación)
- `logo_lasalle.png` (Logo institucional para la interfaz)

### Comando de Compilación

Ejecuta el siguiente comando en la terminal desde la carpeta del proyecto:

```bash
pyinstaller --noconfirm --onefile --windowed --icon="icon.ico" --add-data "logo_lasalle.png;." --add-data "icon.ico;." net_test.py
```

### Notas sobre la Compilación:
- `--onefile`: Genera un único archivo `.exe`.
- `--windowed`: Evita que se abra una ventana de consola al ejecutar el programa (GUI pura).
- `--add-data`: Incluye los recursos externos (logo e icono) dentro del ejecutable.
- El archivo resultante se encontrará en la carpeta `dist/`.

## Uso

1. Selecciona la interfaz de red que deseas diagnosticar.
2. (Opcional) Introduce un dominio web personalizado para testear conectividad.
3. Haz clic en **"Iniciar Diagnóstico Completo"**.
4. Sigue las instrucciones en consola; si falla el DHCP, el programa te permitirá asignar una IP manual de una lista de VLANs predefinidas.
