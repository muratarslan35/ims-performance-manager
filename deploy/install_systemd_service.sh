#!/usr/bin/env bash
set -Eeuo pipefail

ims_path=${1:?IMS application path is required}
release_mode=${2:-heavy}
service_name=ims-performance-manager.service
template_path="$ims_path/deploy/$service_name.in"
worker_service_name=ims-import-worker.service
worker_template_path="$ims_path/deploy/$worker_service_name.in"

test -d "$ims_path"
test -f "$template_path"
test -f "$worker_template_path"
test -x "$ims_path/venv/bin/gunicorn"
case "$release_mode" in
  ui|backend|import|heavy) ;;
  *) echo "Unsupported release mode: $release_mode" >&2; exit 1 ;;
esac

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

# Preserve the same stable production secret across reloads/restarts.
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

# Import/heavy releases must not expose the all-region cockpit until the latest
# completed IMS generation has a complete durable snapshot set. The import gate
# has already verified that no PROCESSING job is active before this script runs.
if [ "$release_mode" = "import" ] || [ "$release_mode" = "heavy" ]; then
  echo "REGION_SNAPSHOT_ACTIVATION|building_latest_before_web_activation"
  PYTHONPATH="$ims_path${PYTHONPATH:+:$PYTHONPATH}" "$ims_path/venv/bin/python" "$ims_path/scripts/backfill_active_region_snapshots.py"
fi

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

# Code-only releases use Gunicorn's HUP reload: new workers boot with the new
# code while old workers finish current requests. Full stop/start is reserved
# for DB/service-level changes. This avoids the graceful-stop timeout on every
# normal deployment.
if sudo systemctl is-active --quiet "$service_name"; then
  if [ "$release_mode" = "heavy" ]; then
    sudo systemctl restart "$service_name"
    echo "SERVICE_ACTIVATION|web=restart|mode=$release_mode"
  else
    sudo systemctl reload "$service_name"
    echo "SERVICE_ACTIVATION|web=reload|mode=$release_mode"
  fi
else
  sudo systemctl start "$service_name"
  echo "SERVICE_ACTIVATION|web=start|mode=$release_mode"
fi
sudo systemctl --no-pager --full status "$service_name"

# The background importer only needs replacement when importer/DB code changed.
# Deploy workflow verifies there is no PROCESSING job before those modes reach
# this script, so no live import can be interrupted by the restart.
if [ "$release_mode" = "import" ] || [ "$release_mode" = "heavy" ]; then
  if sudo systemctl is-active --quiet "$worker_service_name"; then
    sudo systemctl restart "$worker_service_name"
    echo "SERVICE_ACTIVATION|worker=restart|mode=$release_mode"
  else
    sudo systemctl start "$worker_service_name"
    echo "SERVICE_ACTIVATION|worker=start|mode=$release_mode"
  fi
elif ! sudo systemctl is-active --quiet "$worker_service_name"; then
  sudo systemctl start "$worker_service_name"
  echo "SERVICE_ACTIVATION|worker=start|mode=$release_mode"
else
  echo "SERVICE_ACTIVATION|worker=preserved|mode=$release_mode"
fi
sudo systemctl --no-pager --full status "$worker_service_name"

# A runtime deploy is not accepted until the shared dashboard read model is
# proven ready for the exact current IMS/production source identity. Import and
# heavy modes wait for the restarted worker warm-up; backend mode verifies the
# already-running worker/shared snapshot. UI-only releases do not touch the
# dashboard data path and therefore keep the fast UI deploy behavior.
if [ "$release_mode" = "backend" ] || [ "$release_mode" = "import" ] || [ "$release_mode" = "heavy" ]; then
  echo "DASHBOARD_SNAPSHOT_ACTIVATION|waiting_for_active_snapshot"
  PYTHONPATH="$ims_path${PYTHONPATH:+:$PYTHONPATH}" \
    "$ims_path/venv/bin/python" "$ims_path/verify_dashboard_snapshot_production.py" \
    --wait-seconds 120 --poll-seconds 1 --reads 5 --max-read-seconds 2.0
fi
