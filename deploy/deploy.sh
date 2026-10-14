#!/usr/bin/env bash
# Deploy a tagged release on the kiosk, as the kiosk user:
#   /opt/kiosk/deploy.sh v1.2.0        prepare, switch, restart, health check (auto-restore)
#   /opt/kiosk/deploy.sh --prepare v1.2.0
#   /opt/kiosk/deploy.sh --rollback    switch back to the previous release
set -euo pipefail

ROOT=${KIOSK_ROOT:-/opt/kiosk}
REPO=${KIOSK_REPO:-https://github.com/DahamDissanayake/iit-kiosk.git}
RELEASES_URL=${KIOSK_RELEASES_URL:-https://github.com/DahamDissanayake/iit-kiosk/releases/download}
HEALTH_URL=${KIOSK_HEALTH_URL:-http://127.0.0.1:8080/health}
HEALTH_TRIES=${KIOSK_HEALTH_TRIES:-60}
HEALTH_WAIT=${KIOSK_HEALTH_WAIT:-2}
SERVICES=(kiosk-vision kiosk-core)

log() { echo "[deploy] $*"; }
die() { echo "[deploy] $*" >&2; exit 1; }

check_tag() {
  [[ $1 =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "release tags look like v1.2.3, got '$1'"
}

prepare() {
  local tag=$1 dir tmp
  check_tag "$tag"
  dir=$ROOT/releases/$tag
  if [[ -d $dir ]]; then
    log "$tag already prepared"
    return
  fi
  tmp=$dir.tmp
  rm -rf "$tmp"
  log "fetching $tag"
  git clone --quiet --depth 1 --branch "$tag" "$REPO" "$tmp"
  (cd "$tmp" && uv venv --quiet --python /usr/bin/python3 --system-site-packages \
    && uv sync --quiet --frozen --no-dev)
  mkdir -p "$tmp/dashboard/dist"
  curl -fsSL "$RELEASES_URL/$tag/dashboard-dist.tar.gz" | tar -xz -C "$tmp/dashboard/dist"
  mv "$tmp" "$dir"
}

healthy() {
  local i
  for ((i = 0; i < HEALTH_TRIES; i++)); do
    if curl -fsS -o /dev/null "$HEALTH_URL"; then
      return 0
    fi
    sleep "$HEALTH_WAIT"
  done
  return 1
}

current_target() { readlink -f "$ROOT/current" 2>/dev/null || true; }

switch_to() {
  local target=$1 old
  old=$(current_target)
  ln -sfn "$target" "$ROOT/current.new"
  mv -Tf "$ROOT/current.new" "$ROOT/current"
  if [[ -n $old && $old != "$target" ]]; then
    ln -sfn "$old" "$ROOT/previous"
  fi
  systemctl --user restart "${SERVICES[@]}"
}

deploy() {
  local tag=$1 old
  prepare "$tag"
  old=$(current_target)
  switch_to "$ROOT/releases/$tag"
  if healthy; then
    log "$tag is live"
    return
  fi
  if [[ -n $old && -d $old ]]; then
    switch_to "$old"
    healthy && die "$tag failed its health check; restored $(basename "$old")"
    die "$tag failed its health check and $(basename "$old") is not healthy either"
  fi
  die "$tag failed its health check and there is no earlier release"
}

rollback() {
  local prev
  prev=$(readlink -f "$ROOT/previous" 2>/dev/null || true)
  [[ -n $prev && -d $prev && $prev != "$(current_target)" ]] || die "no previous release to roll back to"
  log "rolling back to $(basename "$prev")"
  switch_to "$prev"
  healthy || die "$(basename "$prev") is not healthy"
  log "rolled back to $(basename "$prev")"
}

case "${1:-}" in
  --rollback) rollback ;;
  --prepare) prepare "${2:-}" ;;
  "") die "usage: deploy.sh vX.Y.Z | --prepare vX.Y.Z | --rollback" ;;
  *) deploy "$1" ;;
esac
