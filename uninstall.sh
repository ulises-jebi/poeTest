#!/bin/bash
set -e

# ============================================
#  poeTest - Desinstalador
#  PLANET IGS-4215-8UP2T2S PoE++ CLI Tool
# ============================================

APP_NAME="poeTest"
APP_DIR="/opt/$APP_NAME"
BIN_LINK="/usr/local/bin/$APP_NAME"

echo ""
echo "========================================"
echo "  Desinstalando $APP_NAME"
echo "========================================"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Ejecuta con sudo:"
    echo "        sudo ./uninstall.sh"
    exit 1
fi

# --- Eliminar comando global ---
if [ -f "$BIN_LINK" ]; then
    rm -f "$BIN_LINK"
    echo "[1/2] Comando '$APP_NAME' eliminado de PATH"
else
    echo "[1/2] Comando '$APP_NAME' no encontrado (ya removido)"
fi

# --- Eliminar directorio de instalacion ---
if [ -d "$APP_DIR" ]; then
    rm -rf "$APP_DIR"
    echo "[2/2] Directorio $APP_DIR eliminado"
else
    echo "[2/2] Directorio $APP_DIR no encontrado (ya removido)"
fi

echo ""
echo "  $APP_NAME desinstalado completamente."
echo ""
