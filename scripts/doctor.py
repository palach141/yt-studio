#!/usr/bin/env python3
"""doctor.py - проверка, что yt-studio готов к работе, и первичная настройка.

    python3 doctor.py            # что установлено, что настроено, чего не хватает
    python3 doctor.py --init     # создать ~/.claude/yt-studio/voice.md из шаблона (существующий не трогает)
    python3 doctor.py --json

Обязателен только Python 3.8+. Всё остальное - по желанию, и для каждого пункта сказано, что именно
он открывает.
"""
import json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import guard, parse_args, read_text, banned_words, load_formulas, HOME_DIR, VOICE_PATH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "templates", "voice.md")
OPTIONAL = [
    ("yt-dlp", "fetch.py: субтитры видео и списки каналов одной командой",
     "macOS: brew install yt-dlp | Windows: winget install yt-dlp | любой: python3 -m pip install -U yt-dlp"),
    ("ffmpeg", "черновой рез видео по команде из cuts.py --ffmpeg",
     "macOS: brew install ffmpeg | Windows: winget install ffmpeg"),
    ("whisper", "транскрипт с таймкодами по словам - точный рез пауз",
     "python3 -m pip install -U openai-whisper (нужен ffmpeg)"),
]

def voice_state():
    if not os.path.exists(VOICE_PATH): return "missing"
    text = read_text(VOICE_PATH)
    template = read_text(TEMPLATE) if os.path.exists(TEMPLATE) else ""
    return "template" if text.strip() == template.strip() else "filled"

def main():
    pos, opt = parse_args(sys.argv[1:], flags=("--json", "--init"))
    created = False
    if "--init" in opt and not os.path.exists(VOICE_PATH):
        os.makedirs(HOME_DIR, exist_ok=True)
        shutil.copyfile(TEMPLATE, VOICE_PATH); created = True
    journal = os.path.join(HOME_DIR, "journal.jsonl")
    n_journal = sum(1 for l in open(journal, encoding="utf-8") if l.strip()) if os.path.exists(journal) else 0
    py_ok = sys.version_info >= (3, 8)
    tools = {name: bool(shutil.which(name)) for name, _, _ in OPTIONAL}
    if not tools["yt-dlp"]:
        try:
            import yt_dlp  # noqa: F401
            tools["yt-dlp"] = True
        except ImportError: pass
    try: formulas = len(load_formulas())
    except Exception: formulas = 0                          # noqa: BLE001
    state = {"python": "%d.%d.%d" % sys.version_info[:3], "python_ok": py_ok, "skill_dir": ROOT,
             "formulas": formulas, "voice": voice_state(), "voice_path": VOICE_PATH, "voice_created": created,
             "banned_words": len(banned_words()), "journal_entries": n_journal, "tools": tools,
             "ready": py_ok and formulas > 0}
    if "--json" in opt: print(json.dumps(state, ensure_ascii=False, indent=1)); return
    mark = lambda ok: "ok  " if ok else "нет "
    print(f"\n  yt-studio: {'ГОТОВ К РАБОТЕ' if state['ready'] else 'НЕ ГОТОВ'}\n")
    print(f"    {mark(py_ok)} Python {state['python']}" + ("" if py_ok else "  - нужен 3.8 или новее"))
    print(f"    {mark(formulas > 0)} формулы хука: {formulas}" + ("" if formulas else "  - повреждён data/hooks.json, переустанови скилл"))
    v = state["voice"]
    print(f"    {'ok  ' if v == 'filled' else '-   '} описание голоса (voice.md): " +
          {"missing": "нет - это не мешает работе. С ним тексты звучат как автор; шаблон создаёт doctor.py --init",
           "template": f"шаблон не заполнен ({VOICE_PATH}). Заполни сам или попроси Claude собрать его из транскриптов твоих видео",
           "filled": f"заполнен, запрещённых слов: {state['banned_words']}"}[v] + (" (только что создан)" if created else ""))
    print(f"    {'ok  ' if n_journal else '-   '} журнал: записей {n_journal}" + ("" if n_journal else " - это нормально, он появится после первой публикации"))
    print(f"\n  личные файлы лежат в: {HOME_DIR}")
    print("\n  по желанию:")
    for name, what, how in OPTIONAL:
        print(f"    {mark(tools[name])} {name:<8} {what}" + ("" if tools[name] else f"\n             поставить: {how}"))
    print("\n  без необязательных программ работает всё, кроме перечисленного рядом с ними.\n")
    if not state["ready"]: sys.exit(1)

if __name__ == "__main__":
    guard(main)
