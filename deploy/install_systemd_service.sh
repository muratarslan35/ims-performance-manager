#!/usr/bin/env bash
set -Eeuo pipefail

ims_path=${1:?IMS application path is required}
service_name=ims-performance-manager.service
template_path="$ims_path/deploy/$service_name.in"

test -d "$ims_path"
test -f "$template_path"
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
trap 'rm -f "$unit_tmp"' EXIT

sed \
  -e "s|@IMS_PATH@|$escaped_path|g" \
  -e "s|@IMS_USER@|$ims_user|g" \
  -e "s|@IMS_GROUP@|$ims_group|g" \
  "$template_path" > "$unit_tmp"

sudo install -o root -g root -m 0644 "$unit_tmp" "/etc/systemd/system/$service_name"
sudo systemctl daemon-reload
sudo systemctl enable "$service_name"

# The first managed deployment may replace the legacy `python run.py`
# process.  Stop only the verified process owned by this application path.
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

if sudo systemctl is-active --quiet "$service_name"; then
  sudo systemctl reload "$service_name"
else
  sudo systemctl start "$service_name"
fi

sudo systemctl --no-pager --full status "$service_name"
