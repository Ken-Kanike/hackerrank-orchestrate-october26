#!/bin/sh
# Docker entrypoint — selects CLI or API mode
# Usage: CMD ["cli"]  or  CMD ["api"]
set -e

MODE="${1:-cli}"

case "$MODE" in
  cli)
    shift || true
    echo "[entrypoint] Running CLI pipeline ($*)"
    exec python code/main.py "$@"
    ;;
  api)
    shift || true
    echo "[entrypoint] Starting API server on :${PORT:-8000}"
    exec uvicorn server:app \
      --host 0.0.0.0 \
      --port "${PORT:-8000}" \
      --workers 1 \
      --timeout-keep-alive 120 \
      "$@"
    ;;
  *)
    echo "Usage: docker run ghost-audit [cli|api] [extra flags]"
    exit 1
    ;;
esac
