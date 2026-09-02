#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$project_root/.venv/bin/python"
demo_port="${ORBITGUARD_PORT:-8501}"

if [[ ! "$demo_port" =~ ^[0-9]+$ ]] || (( demo_port < 1024 || demo_port > 65535 )); then
  echo "ORBITGUARD_PORT must be an integer between 1024 and 65535." >&2
  exit 1
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Demo environment missing. Run: python3 -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements-dev.txt" >&2
  exit 1
fi

if ! "$python_bin" -c "import streamlit, orbit_guard" 2>/dev/null; then
  echo "Demo dependencies missing. Activate .venv and run: python -m pip install -r requirements-dev.txt" >&2
  exit 1
fi

port_state="$("$python_bin" - "$demo_port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket() as probe:
    occupied = probe.connect_ex(("127.0.0.1", port)) == 0
print("occupied" if occupied else "free")
PY
)"

if [[ "$port_state" == "occupied" ]]; then
  echo "Port $demo_port is already in use; the launcher cannot verify which app owns it." >&2
  echo "Close that process, or launch a fresh verified instance with: ORBITGUARD_PORT=8502 ./scripts/run_demo.sh" >&2
  exit 1
fi

cd "$project_root"
echo "Starting UK Orbit Guard at http://127.0.0.1:$demo_port"
exec "$python_bin" -m streamlit run app.py --server.address 127.0.0.1 --server.port "$demo_port"
