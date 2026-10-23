#!/usr/bin/env bash
# Deploy to the current kubectl context. See deploy_k8s.py --help.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$ROOT/deploy_k8s.py" "$@"
fi
exec python "$ROOT/deploy_k8s.py" "$@"
