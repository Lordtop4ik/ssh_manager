#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  SSH Manager — установщик
#  Ubuntu 24.04
#  Использование:
#    curl -fsSL https://raw.githubusercontent.com/YOUR/REPO/main/install.sh | sudo bash
# ─────────────────────────────────────────────────────────

set -euo pipefail

GREEN="\033[92m"
RED="\033[91m"
YELLOW="\033[93m"
CYAN="\033[96m"
BOLD="\033[1m"
RESET="\033[0m"

INSTALL_PATH="/usr/local/bin/ssh_manager"
SCRIPT_URL="https://raw.githubusercontent.com/Lordtop4ik/ssh_manager/refs/heads/main/ssh_manager.py"

ok()   { echo -e "${GREEN}✓ $*${RESET}"; }
err()  { echo -e "${RED}✗ $*${RESET}"; exit 1; }
info() { echo -e "${CYAN}→ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠ $*${RESET}"; }

# ── Проверка root ──────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Запусти установщик с правами root: sudo bash install.sh"
fi

# ── Проверка Ubuntu 24.04 ──────────────────────────────────
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        warn "Обнаружена не Ubuntu ($ID). Продолжение на свой страх и риск."
    fi
fi

echo ""
echo -e "${CYAN}${BOLD}════════════════════════════════════════${RESET}"
echo -e "${CYAN}${BOLD}         SSH Manager — Установка        ${RESET}"
echo -e "${CYAN}${BOLD}════════════════════════════════════════${RESET}"
echo ""

# ── Python3 ───────────────────────────────────────────────
info "Проверяю Python3..."
if ! command -v python3 &>/dev/null; then
    info "Python3 не найден. Устанавливаю..."
    apt-get update -q
    apt-get install -y -q python3
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER найден."

# ── openssh-server ────────────────────────────────────────
info "Проверяю openssh-server..."
if ! command -v sshd &>/dev/null; then
    info "sshd не найден. Устанавливаю openssh-server..."
    apt-get update -q
    apt-get install -y -q openssh-server
fi
ok "openssh-server установлен."

# ── Копируем скрипт ───────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SCRIPT="$SCRIPT_DIR/ssh_manager.py"

if [[ -f "$LOCAL_SCRIPT" ]]; then
    info "Нашёл локальный ssh_manager.py — устанавливаю его."
    cp "$LOCAL_SCRIPT" "$INSTALL_PATH"
else
    # Скачиваем из GitHub
    if command -v curl &>/dev/null; then
        info "Скачиваю ssh_manager.py с GitHub..."
        curl -fsSL "$SCRIPT_URL" -o "$INSTALL_PATH"
    elif command -v wget &>/dev/null; then
        wget -q "$SCRIPT_URL" -O "$INSTALL_PATH"
    else
        err "Не найдены curl и wget. Установи один из них."
    fi
fi

# ── Права ─────────────────────────────────────────────────
chmod +x "$INSTALL_PATH"
chown root:root "$INSTALL_PATH"
ok "Установлено: $INSTALL_PATH"

# ── Резервная копия sshd_config ───────────────────────────
if [[ -f /etc/ssh/sshd_config && ! -f /etc/ssh/sshd_config.bak ]]; then
    cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
    ok "Резервная копия: /etc/ssh/sshd_config.bak"
fi

# ── Финал ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}   Установка завершена успешно!         ${RESET}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════${RESET}"
echo ""
echo -e "  Запуск:  ${BOLD}sudo ssh_manager${RESET}"
echo ""
