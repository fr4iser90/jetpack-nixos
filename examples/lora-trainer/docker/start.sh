#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/lib/start-docker-example.sh" "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
