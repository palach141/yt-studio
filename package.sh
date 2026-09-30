#!/bin/sh
# Собирает dist/yt-studio.zip для загрузки в claude.ai (Настройки -> Возможности -> Навыки).
set -eu
cd "$(dirname "$0")"
rm -rf dist && mkdir -p dist/yt-studio
for item in SKILL.md LICENSE scripts references data templates; do cp -R "$item" dist/yt-studio/; done
find dist -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
(cd dist && zip -qr yt-studio.zip yt-studio && rm -rf yt-studio)
echo "готово: dist/yt-studio.zip"
