#!/usr/bin/env bash
# Started by labwc autostart: rotate the screen, wait for kiosk-core, run Chromium full screen.
set -euo pipefail

ROTATION=${KIOSK_ROTATION:-90}
URL=${KIOSK_URL:-http://127.0.0.1:8765/}

output=$(wlr-randr | awk '/^[A-Z]/ {print $1; exit}')
if [[ -n ${output:-} ]]; then
  wlr-randr --output "$output" --transform "$ROTATION" || true
fi

until curl -fsS -o /dev/null "$URL"; do sleep 1; done

browser=$(command -v chromium-browser || command -v chromium)
while true; do
  "$browser" \
    --kiosk --noerrdialogs --disable-infobars --no-first-run \
    --autoplay-policy=no-user-gesture-required \
    --disable-session-crashed-bubble --disable-features=TranslateUI \
    --overscroll-history-navigation=0 --disable-pinch \
    --check-for-update-interval=31536000 --password-store=basic \
    "$URL" || true
  sleep 2
done
