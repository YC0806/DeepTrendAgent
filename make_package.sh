#!/usr/bin/env bash
# Build a deployment archive without local secrets, history, logs, or caches.
set -euo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_PARENT="$(dirname -- "$PROJECT_DIR")"
PROJECT_NAME="$(basename -- "$PROJECT_DIR")"
OUTPUT_PATH="${1:-$PROJECT_DIR/deeptrend-agent-$(date +%Y%m%d-%H%M%S).tar.gz}"

case "$OUTPUT_PATH" in
  /*) ;;
  *) OUTPUT_PATH="$PWD/$OUTPUT_PATH" ;;
esac

mkdir -p "$(dirname -- "$OUTPUT_PATH")"

COPYFILE_DISABLE=1 tar -czf "$OUTPUT_PATH" \
  -C "$PROJECT_PARENT" \
  --exclude='*/.env' \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='*/.DS_Store' \
  "$PROJECT_NAME/.opencode/skills" \
  "$PROJECT_NAME/bin" \
  "$PROJECT_NAME/deploy" \
  "$PROJECT_NAME/src" \
  "$PROJECT_NAME/tests" \
  "$PROJECT_NAME/.env.example" \
  "$PROJECT_NAME/AGENTS.md" \
  "$PROJECT_NAME/AGENTS_RUN.md" \
  "$PROJECT_NAME/LICENSE" \
  "$PROJECT_NAME/README.md" \
  "$PROJECT_NAME/make_package.sh"

FORBIDDEN='(^|/)\.env($|/)|(^|/)(\.git|logs|tmp|output|node_modules|\.pytest_cache|\.claude|__pycache__)(/|$)'
ARCHIVE_CONTENTS="$(tar -tzf "$OUTPUT_PATH")"
if grep -E "$FORBIDDEN" <<< "$ARCHIVE_CONTENTS" >/dev/null; then
  echo "Refusing to use archive: excluded files were found in $OUTPUT_PATH" >&2
  exit 1
fi

if command -v shasum >/dev/null 2>&1; then
  DIGEST="$(shasum -a 256 "$OUTPUT_PATH" | awk '{print $1}')"
else
  DIGEST="$(sha256sum "$OUTPUT_PATH" | awk '{print $1}')"
fi

printf 'Archive: %s\nSHA-256: %s\n' "$OUTPUT_PATH" "$DIGEST"
