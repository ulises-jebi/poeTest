# poeTest

CLI tool para monitoreo y control de puertos PoE en el switch **PLANET IGS-4215-8UP2T2S**.

Usa SNMP + Web Scraping para obtener datos en tiempo real de consumo, corriente, temperatura y estado de cada puerto PoE++.

---

## Instalación en Linux (Ubuntu / Raspberry Pi OS)

```bash
git clone https://github.com/TU-USUARIO/poeTest.git
cd poeTest
chmod +x install.sh uninstall.sh
sudo ./install.sh
```

El instalador automáticamente:
- Verifica e instala Python 3.11+ si no está presente
- Crea un entorno virtual aislado en `/opt/poeTest/venv/`
- Instala todas las dependencias dentro del venv
- Registra el comando `poeTest` en el PATH del sistema

Después de instalar, ejecutar desde cualquier directorio:
```bash
poeTest -r status
```

### Desinstalación Linux
```bash
sudo ./uninstall.sh
```

---

## Instalación en Windows

1. Instalar [Python 3.11](https://www.python.org/downloads/) (marcar "Add to PATH")
2. Abrir una terminal en la carpeta del proyecto e instalar dependencias:
```cmd
py -3.11 -m pip install -r requirements.txt
```
3. Agregar la carpeta del proyecto al PATH del sistema, o copiar `poeTest.bat` y `poeTest.py` a una carpeta que ya esté en el PATH (ej: `C:\Program Files\poeTest\`)

Después de instalar, ejecutar desde cualquier directorio:
```cmd
poeTest -r status
```

---

## Uso

```bash
# Lectura
poeTest -r status              # Resumen rápido
poeTest -r ports               # Tabla detallada de puertos
poeTest -r port3               # Detalle del puerto 3
poeTest -r power               # Datos de potencia
poeTest -r system              # Info del sistema
poeTest -r watch,5             # Monitor en vivo cada 5s
poeTest -r csv                 # Exportar snapshot a CSV
poeTest -r log                 # Agregar línea al log continuo

# Escritura
poeTest -w port3,1             # Habilitar puerto 3
poeTest -w port3,0             # Deshabilitar puerto 3
poeTest -w port3,r             # Reiniciar puerto 3 (off/on 5s)
poeTest -w port3,r,10          # Reiniciar con espera de 10s
poeTest -w port1,1 port5,0    # Múltiples puertos a la vez

# Ayuda
poeTest help
```

## Requisitos

- **Python 3.11+** (en Linux el instalador lo resuelve automáticamente)
- Acceso de red al switch (192.168.1.90)
- SNMP habilitado en el switch (community: public)
- **Linux:** Ubuntu / Debian / Raspberry Pi OS (64-bit)
- **Windows:** Windows 10/11 con Python 3.11 instalado

## Configuración

La IP del switch y credenciales se configuran en `SWITCH_CONFIG` dentro de `poeTest.py`:

```python
SWITCH_CONFIG = {
    "host":       "192.168.1.90",
    "snmp_port":  161,
    "community":  "public",
    "web_user":   "admin",
    "web_pass":   "JebiPoe1!",
}
```

## Estructura del proyecto

```
poeTest/
├── poeTest.py          # Script principal
├── poeTest.bat         # Launcher para Windows
├── requirements.txt    # Dependencias Python
├── install.sh          # Instalador Linux (crea venv + comando global)
├── uninstall.sh        # Desinstalador Linux
└── README.md
```
