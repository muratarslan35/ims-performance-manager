#!/usr/bin/env bash
set -Eeuo pipefail

ims_path=${1:?IMS application path is required}
service_name=ims-performance-manager.service
template_path="$ims_path/deploy/$service_name.in"
worker_service_name=ims-import-worker.service
worker_template_path="$ims_path/deploy/$worker_service_name.in"

test -d "$ims_path"
test -f "$template_path"
test -f "$worker_template_path"
test -x "$ims_path/venv/bin/gunicorn"
mkdir -p \
  "$ims_path/instance" \
  "$ims_path/uploads" \
  "$ims_path/logs" \
  "$ims_path/reports" \
  "$ims_path/backups" \
  "$ims_path/temp"

ims_user=$(id -un)
ims_group=$(id -gn)
escaped_path=${ims_path//|/\\|}
unit_tmp=$(mktemp)
worker_unit_tmp=$(mktemp)
runtime_env_tmp=$(mktemp)
trap 'rm -f "$unit_tmp" "$worker_unit_tmp" "$runtime_env_tmp"' EXIT

# The legacy Flask process used the persistent instance secret when no
# SECRET_KEY existed in .env. Preserve that same key for Gunicorn so existing
# sessions remain valid and production never falls back to an ephemeral key.
if ! grep -Eq '^[[:space:]]*SECRET_KEY[[:space:]]*=' "$ims_path/.env" 2>/dev/null; then
  secret_path="$ims_path/instance/.secret_key"
  if [ ! -s "$secret_path" ]; then
    umask 077
    "$ims_path/venv/bin/python" - <<'PY' > "$secret_path"
import secrets
print(secrets.token_urlsafe(48))
PY
  fi
  secret_key=$(tr -d '\r\n' < "$secret_path")
  test -n "$secret_key"
  printf 'SECRET_KEY=%s\n' "$secret_key" > "$runtime_env_tmp"
  sudo install -o root -g root -m 0600 "$runtime_env_tmp" /etc/ims-performance-manager.env
else
  : > "$runtime_env_tmp"
  sudo install -o root -g root -m 0600 "$runtime_env_tmp" /etc/ims-performance-manager.env
fi

sed \
  -e "s|@IMS_PATH@|$escaped_path|g" \
  -e "s|@IMS_USER@|$ims_user|g" \
  -e "s|@IMS_GROUP@|$ims_group|g" \
  "$template_path" > "$unit_tmp"
sed \
  -e "s|@IMS_PATH@|$escaped_path|g" \
  -e "s|@IMS_USER@|$ims_user|g" \
  -e "s|@IMS_GROUP@|$ims_group|g" \
  "$worker_template_path" > "$worker_unit_tmp"

sudo install -o root -g root -m 0644 "$unit_tmp" "/etc/systemd/system/$service_name"
sudo install -o root -g root -m 0644 "$worker_unit_tmp" "/etc/systemd/system/$worker_service_name"
sudo systemctl daemon-reload
sudo systemctl enable "$service_name"
sudo systemctl enable "$worker_service_name"

# The first managed deployment may replace the legacy `python run.py`
# process. Stop only the verified process owned by this application path.
if ! sudo systemctl is-active --quiet "$service_name"; then
  legacy_pid=$(ss -ltnp | sed -n 's/.*:8000.*pid=\([0-9]*\).*/\1/p' | head -1)
  if [ -n "$legacy_pid" ]; then
    legacy_command=$(ps -p "$legacy_pid" -o args= || true)
    legacy_cwd=$(readlink -f "/proc/$legacy_pid/cwd" 2>/dev/null || true)
    if [ "$legacy_cwd" = "$ims_path" ] && [[ "$legacy_command" =~ (run\.py|gunicorn) ]]; then
      kill "$legacy_pid"
    else
      echo "Port 8000 is owned by an unexpected process; refusing to stop it: $legacy_command" >&2
      exit 1
    fi
  fi
fi

# Production acceptance and representative performance gates run before this
# script. Once they pass, restart every managed worker so no process continues
# serving code or in-memory caches from the previous release.
if sudo systemctl is-active --quiet "$service_name"; then
  sudo systemctl restart "$service_name"
else
  sudo systemctl start "$service_name"
fi

sudo systemctl --no-pager --full status "$service_name"
if sudo systemctl is-active --quiet "$worker_service_name"; then
  sudo systemctl restart "$worker_service_name"
else
  sudo systemctl start "$worker_service_name"
fi
sudo systemctl --no-pager --full status "$worker_service_name"
