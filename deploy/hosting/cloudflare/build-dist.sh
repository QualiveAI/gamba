#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
out="$repo_root/deploy/hosting/cloudflare/dist"
rm -rf "$out"
mkdir -p "$out/app"
cp -R "$repo_root/landing/." "$out/"
cp -R "$repo_root/frontend/." "$out/app/"
cp "$(dirname "$0")/_redirects" "$out/_redirects"
cp "$(dirname "$0")/_headers" "$out/_headers"
rm -rf "$out/app/node_modules" "$out/app/.cache" "$out/app/test-results" "$out/app/pw-run-"*.log
printf 'Cloudflare Pages dist готов: %s\n' "$out"
