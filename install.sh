#!/bin/bash
set -e

# ============================================
#  poeTest - Instalador para Ubuntu/Debian
#  PLANET IGS-4215-8UP2T2S PoE++ CLI Tool
#  Requiere: Python 3.11+
# ============================================

APP_NAME="poeTest"
APP_DIR="/opt/$APP_NAME"
VENV_DIR="$APP_DIR/venv"
BIN_LINK="/usr/local/bin/$APP_NAME"
SCRIPT_NAME="poeTest.py"
PYTHON_MIN="3.11"

echo ""
echo "========================================"
echo "  Instalando $APP_NAME"
echo "  PLANET IGS-4215-8UP2T2S PoE CLI Tool"
echo "========================================"
echo ""

# --- Verificar que se ejecuta como root ---
if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Ejecuta el instalador con sudo:"
    echo "        sudo ./install.sh"
    exit 1
fi

# --- Verificar archivos necesarios ---
if [ ! -f "$SCRIPT_NAME" ]; then
    echo "[ERROR] No se encontro $SCRIPT_NAME en el directorio actual."
    echo "        Ejecuta este script desde la carpeta del proyecto."
    exit 1
fi

if [ ! -f "requirements.txt" ]; then
    echo "[ERROR] No se encontro requirements.txt en el directorio actual."
    exit 1
fi

# ==============================================================
# FUNCION: Buscar Python 3.11+
# ==============================================================
find_python() {
    # Buscar python3.11, python3.12, python3.13... o python3 si cumple version
    for cmd in python3.11 python3.12 python3.13 python3; do
        if command -v "$cmd" > /dev/null 2>&1; then
            ver=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

# ==============================================================
# PASO 1: Verificar / Instalar Python 3.11+
# ==============================================================
echo "[1/6] Verificando Python >= $PYTHON_MIN..."

PYTHON_CMD=$(find_python) || PYTHON_CMD=""

if [ -n "$PYTHON_CMD" ]; then
    PYTHON_VER=$("$PYTHON_CMD" --version 2>&1)
    echo "       Encontrado: $PYTHON_VER ($PYTHON_CMD)"
else
    echo "       Python >= $PYTHON_MIN no encontrado. Instalando..."
    apt update -qq

    # Intentar instalar python3.11 desde los repos del sistema
    if apt-cache show python3.11 > /dev/null 2>&1; then
        apt install -y python3.11 python3.11-venv python3.11-dev > /dev/null 2>&1
        PYTHON_CMD="python3.11"

    # Si no esta en repos, intentar con deadsnakes PPA (Ubuntu)
    elif command -v add-apt-repository > /dev/null 2>&1; then
        echo "       Agregando repositorio deadsnakes..."
        apt install -y software-properties-common > /dev/null 2>&1
        add-apt-repository -y ppa:deadsnakes/ppa > /dev/null 2>&1
        apt update -qq
        apt install -y python3.11 python3.11-venv python3.11-dev > /dev/null 2>&1
        PYTHON_CMD="python3.11"

    # Ultimo recurso: compilar desde fuente
    else
        echo "       Compilando Python 3.11 desde fuente (puede tardar 10-15 min)..."
        apt install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev \
            libnss3-dev libssl-dev libreadline-dev libffi-dev libsqlite3-dev \
            wget libbz2-dev > /dev/null 2>&1

        cd /tmp
        wget -q https://www.python.org/ftp/python/3.11.11/Python-3.11.11.tgz
        tar -xf Python-3.11.11.tgz
        cd Python-3.11.11
        ./configure --enable-optimizations --prefix=/usr/local > /dev/null 2>&1
        make -j$(nproc) > /dev/null 2>&1
        make altinstall > /dev/null 2>&1
        cd -
        rm -rf /tmp/Python-3.11.11 /tmp/Python-3.11.11.tgz
        PYTHON_CMD="python3.11"
    fi

    # Verificar que se instalo correctamente
    PYTHON_CMD=$(find_python) || PYTHON_CMD=""
    if [ -z "$PYTHON_CMD" ]; then
        echo ""
        echo "[ERROR] No se pudo instalar Python >= $PYTHON_MIN"
        echo "        Instala Python 3.11+ manualmente y vuelve a ejecutar."
        exit 1
    fi

    PYTHON_VER=$("$PYTHON_CMD" --version 2>&1)
    echo "       Instalado: $PYTHON_VER ($PYTHON_CMD)"
fi

# --- Verificar que tiene venv ---
if ! "$PYTHON_CMD" -m venv --help > /dev/null 2>&1; then
    echo "       Instalando modulo venv..."
    # Extraer version corta (3.11, 3.12, etc.)
    PY_SHORT=$("$PYTHON_CMD" --version 2>&1 | grep -oP '\d+\.\d+')
    apt install -y "python${PY_SHORT}-venv" > /dev/null 2>&1 || \
    apt install -y python3-venv > /dev/null 2>&1
fi

# --- Instalar dependencias del sistema ---
echo "[2/6] Instalando dependencias del sistema..."
apt install -y snmp snmp-mibs-downloader > /dev/null 2>&1 || \
apt install -y snmp > /dev/null 2>&1

echo "       OK"

# --- Crear directorio de instalacion ---
echo "[3/6] Copiando archivos a $APP_DIR..."

if [ -d "$APP_DIR" ]; then
    echo "       Instalacion previa detectada, reemplazando..."
    rm -rf "$APP_DIR"
fi

mkdir -p "$APP_DIR"
cp "$SCRIPT_NAME" "$APP_DIR/"
cp requirements.txt "$APP_DIR/"

echo "       OK"

# --- Crear entorno virtual e instalar dependencias Python ---
echo "[4/6] Creando entorno virtual con $PYTHON_CMD..."
"$PYTHON_CMD" -m venv "$VENV_DIR"
echo "       OK"

echo "[5/6] Instalando dependencias Python..."
"$VENV_DIR/bin/pip" install --upgrade pip > /dev/null 2>&1
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" > /dev/null 2>&1
echo "       OK"

# --- Crear comando global ---
echo "[6/6] Creando comando '$APP_NAME'..."

cat > "$BIN_LINK" << WRAPPER
#!/bin/bash
# poeTest - PLANET IGS-4215-8UP2T2S PoE++ CLI Tool
# Requiere acceso de red al switch (192.168.1.90)
$APP_DIR/venv/bin/python $APP_DIR/$SCRIPT_NAME "\$@"
WRAPPER

chmod +x "$BIN_LINK"
echo "       OK"

# --- Verificar instalacion ---
INSTALLED_PY=$("$VENV_DIR/bin/python" --version 2>&1)

echo ""
echo "========================================"
echo "  Instalacion completada!"
echo "========================================"
echo ""
echo "  Python:  $INSTALLED_PY"
echo "  Ruta:    $APP_DIR"
echo ""
echo "  LECTURA:"
echo "    poeTest -r status          Resumen rapido"
echo "    poeTest -r ports           Tabla de puertos"
echo "    poeTest -r Port3           Detalle puerto 3"
echo "    poeTest -r power           Datos de potencia"
echo "    poeTest -r system          Info del sistema"
echo "    poeTest -r watch,5         Monitor cada 5s"
echo "    poeTest -r csv             Exportar a CSV"
echo "    poeTest -r log             Agregar al log"
echo ""
echo "  ESCRITURA:"
echo "    poeTest -w Port3,1         Habilitar puerto 3"
echo "    poeTest -w Port3,0         Deshabilitar puerto 3"
echo "    poeTest -w Port3,r         Reiniciar puerto 3"
echo ""
echo "  AYUDA:"
echo "    poeTest help"
echo ""
echo "  Desinstalar:  sudo ./uninstall.sh"
echo ""
