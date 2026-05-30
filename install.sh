#!/usr/bin/env bash
# CIN Agent — Install / Upgrade script
# Usage: sudo ./install.sh [username]
# ────────────────────────────────────────────────────────────────

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

BOT_USER="${1:-$SUDO_USER}"
INSTALL_DIR="/opt/cin_agent"
ENV_FILE="/etc/cin_agent/env"
SERVICE_NAME="cin-agent@${BOT_USER}"

log() { echo -e "${GREEN}▶ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err() { echo -e "${RED}✗ $1${NC}"; exit 1; }

[[ $EUID -ne 0 ]] && err "Run as root: sudo ./install.sh [username]"
[[ -z "$BOT_USER" ]] && err "Specify a username: sudo ./install.sh youruser"

log "Installing CIN Agent for user: $BOT_USER"

# ── Dependencies ──────────────────────────────────────────────────
log "Installing system packages..."
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip curl

# ── Install Directory ─────────────────────────────────────────────
log "Setting up $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -f telegram_bot.py command_parser.py shell_ghost.py memory.py "$INSTALL_DIR/"
chown -R "$BOT_USER:$BOT_USER" "$INSTALL_DIR"

# ── Python venv ───────────────────────────────────────────────────
log "Creating Python venv..."
sudo -u "$BOT_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$BOT_USER" "$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u "$BOT_USER" "$INSTALL_DIR/venv/bin/pip" install -q \
    python-telegram-bot \
    httpx

# ── Environment File ──────────────────────────────────────────────
mkdir -p /etc/cin_agent
chmod 700 /etc/cin_agent

if [[ ! -f "$ENV_FILE" ]]; then
    log "Creating environment file at $ENV_FILE"
    cat > "$ENV_FILE" <<'ENVEOF'
# CIN Agent Configuration
# Edit this file, then: sudo systemctl restart cin-agent@<user>

# REQUIRED
TELEGRAM_BOT_TOKEN=your_token_here

# Optional: restrict to specific Telegram user IDs (comma-separated)
# ALLOWED_USER_IDS=123456789,987654321

# Ollama settings
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Optional: Anthropic fallback (leave empty to disable)
# ANTHROPIC_API_KEY=sk-ant-...

# Data directory
CIN_DATA_DIR=__CIN_DATA_DIR__
ENVEOF
    # Resolve the bot user's home directory and fill in the data dir, so the
    # config never ships a hardcoded developer path.
    BOT_HOME="$(getent passwd "$BOT_USER" | cut -d: -f6)"
    BOT_HOME="${BOT_HOME:-/home/$BOT_USER}"
    sed -i "s|__CIN_DATA_DIR__|${BOT_HOME}/.cin_agent|g" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    warn "Edit $ENV_FILE and add your TELEGRAM_BOT_TOKEN before starting"
else
    log "Environment file already exists, skipping (won't overwrite)"
fi

# ── systemd Service ───────────────────────────────────────────────
log "Installing systemd service..."
cp cin-agent@.service /etc/systemd/system/
sed -i "s|/opt/cin_agent/venv|$INSTALL_DIR/venv|g" /etc/systemd/system/cin-agent@.service
systemctl daemon-reload

# ── Enable & (Maybe) Start ────────────────────────────────────────
systemctl enable "$SERVICE_NAME"

# Check if token is configured
if grep -q "your_token_here" "$ENV_FILE" 2>/dev/null; then
    warn "Bot NOT started — configure $ENV_FILE first"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. sudo nano $ENV_FILE"
    echo "  2. Set TELEGRAM_BOT_TOKEN and ALLOWED_USER_IDS"
    echo "  3. sudo systemctl start $SERVICE_NAME"
else
    log "Starting service..."
    systemctl restart "$SERVICE_NAME" || warn "Start failed — check: journalctl -u $SERVICE_NAME -n 50"
fi

echo ""
log "Installation complete!"
echo ""
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo "  Config:  sudo nano $ENV_FILE"
echo "  Upgrade: sudo ./install.sh $BOT_USER"
