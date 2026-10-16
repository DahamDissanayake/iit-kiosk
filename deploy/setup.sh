#!/usr/bin/env bash
# One-time setup of a fresh Raspberry Pi OS (64-bit, desktop) for the kiosk.
# Image the card with Raspberry Pi Imager: user "kiosk", hostname "kiosk", Wi-Fi, SSH on.
# Then, on the Pi:
#   git clone --branch vX.Y.Z https://github.com/DahamDissanayake/iit-kiosk.git /tmp/kiosk
#   sudo bash /tmp/kiosk/deploy/setup.sh vX.Y.Z
set -euo pipefail

TAG=${1:?usage: setup.sh vX.Y.Z}
KUSER=${KIOSK_USER:-kiosk}
SRC=$(cd "$(dirname "$0")/.." && pwd)

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

KHOME=$(getent passwd "$KUSER" | cut -d: -f6)
KUID=$(id -u "$KUSER")
as_kiosk() { sudo -u "$KUSER" XDG_RUNTIME_DIR="/run/user/$KUID" "$@"; }

echo "== packages"
apt-get update
apt-get install -y git curl sqlite3 rsync jq wlr-randr python3-picamera2 chromium-browser

echo "== freeze OS updates for the event"
systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
mapfile -t held < <(dpkg-query -W -f='${Package}\n' 'chromium*' 'libcamera*' 'rpicam*' 'python3-picamera2' 2>/dev/null || true)
((${#held[@]})) && apt-mark hold "${held[@]}"

echo "== uv"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh \
  | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh

echo "== folders and secrets"
install -d -o "$KUSER" -g "$KUSER" /opt/kiosk /opt/kiosk/releases /opt/kiosk/models \
  /var/lib/kiosk /var/lib/kiosk/backups
if [[ ! -f /var/lib/kiosk/.env ]]; then
  umask 077
  printf 'LLM_API_KEY=\nSESSION_SECRET=%s\nBACKUP_TARGET=\n' "$(openssl rand -hex 32)" \
    > /var/lib/kiosk/.env
  chown "$KUSER:$KUSER" /var/lib/kiosk/.env
fi
install -m 755 -o "$KUSER" -g "$KUSER" "$SRC/deploy/deploy.sh" /opt/kiosk/deploy.sh

echo "== logs, sudo rule, desktop autologin"
install -D -m 644 "$SRC/deploy/journald-kiosk.conf" /etc/systemd/journald.conf.d/kiosk.conf
systemctl restart systemd-journald
install -m 440 "$SRC/deploy/sudoers-kiosk" /etc/sudoers.d/kiosk
visudo -cf /etc/sudoers.d/kiosk
raspi-config nonint do_boot_behaviour B4

echo "== user services and browser autostart"
install -d -o "$KUSER" -g "$KUSER" "$KHOME/.config/systemd/user" "$KHOME/.config/labwc"
install -m 644 -o "$KUSER" -g "$KUSER" "$SRC"/deploy/systemd/*.service "$SRC"/deploy/systemd/*.timer \
  "$KHOME/.config/systemd/user/"
install -m 644 -o "$KUSER" -g "$KUSER" "$SRC/deploy/labwc-autostart" "$KHOME/.config/labwc/autostart"
loginctl enable-linger "$KUSER"

echo "== release $TAG and models"
as_kiosk /opt/kiosk/deploy.sh --prepare "$TAG"
ln -sfn "/opt/kiosk/releases/$TAG" /opt/kiosk/current
chown -h "$KUSER:$KUSER" /opt/kiosk/current
as_kiosk env KIOSK_MODELS_DIR=/opt/kiosk/models HF_HOME=/opt/kiosk/models/hf \
  /opt/kiosk/current/.venv/bin/python -m models.download
as_kiosk env KIOSK_MODELS_DIR=/opt/kiosk/models HF_HOME=/opt/kiosk/models/hf \
  /opt/kiosk/current/.venv/bin/python -c \
  "from core.config import load_config; from core.rag.ingest import make_embedder; \
from voice.stt import make_transcriber; c = load_config('/opt/kiosk/current/config.toml'); \
make_embedder(c); make_transcriber(c['voice']); print('models warm')"

echo "== remote access"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh

as_kiosk systemctl --user daemon-reload
as_kiosk systemctl --user enable kiosk-core kiosk-vision kiosk-backup.timer

cat <<EOF

Setup done. Still to do by hand:
  1. sudo tailscale up --ssh                 (log in to the team tailnet)
  2. sudo -u $KUSER nano /var/lib/kiosk/.env  (set LLM_API_KEY; BACKUP_TARGET optional)
  3. sudo -u $KUSER /opt/kiosk/current/.venv/bin/python -m core.admin set-pin \\
       --config /opt/kiosk/current/config.toml   (with KIOSK_DATA_DIR=/var/lib/kiosk)
  4. If [voice] mode = "service": systemctl --user enable kiosk-voice (as $KUSER)
  5. sudo reboot
EOF
