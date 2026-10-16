#!/bin/sh
set -eu

web_root="${STUDIO_WEB_ROOT:-/usr/share/nginx/html}"
source_sha="$(cat "$web_root/source-sha")"
if [ -z "$source_sha" ] && [ -z "${STUDIO_IMAGE_DIGEST:-}" ]; then
  exit 0
fi
test -n "$source_sha"
test -n "$STUDIO_IMAGE_DIGEST"
printf '{"source_sha":"%s","digest":"%s"}\n' "$source_sha" "$STUDIO_IMAGE_DIGEST" \
  > "$web_root/release-identity.json"
