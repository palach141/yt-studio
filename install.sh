#!/bin/sh
# Установка yt-studio для Claude Code (macOS, Linux, WSL, Git Bash).
# Запуск из папки скилла: sh install.sh          Удаление: sh install.sh --uninstall
# Личные данные (voice.md, журнал) лежат в ~/.claude/yt-studio и при обновлении и удалении не трогаются.
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/yt-studio"

if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$DEST"
  echo "yt-studio удалён. voice.md и журнал остались в ~/.claude/yt-studio"
  exit 0
fi

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Нужен Python 3.8 или новее. macOS: brew install python   Ubuntu/Debian: sudo apt install python3" >&2
  exit 1
fi
[ -f "$SRC/SKILL.md" ] || { echo "Рядом с install.sh нет SKILL.md - запускай скрипт из папки скилла." >&2; exit 1; }

if [ "$SRC" != "$DEST" ]; then
  rm -rf "$DEST"
  mkdir -p "$DEST"
  for item in SKILL.md README.md LICENSE scripts references data templates; do
    cp -R "$SRC/$item" "$DEST/"
  done
  find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
fi

"$PY" "$DEST/scripts/doctor.py" --init
echo "Установлено в $DEST"
echo "Перезапусти Claude Code и напиши: \"что умеет yt-studio?\" или сразу \"придумай хук для видео про ...\""
