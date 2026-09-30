#!/usr/bin/env python3
"""speech.py - сколько сценарий звучит вслух и нет ли в нём слов не из голоса автора, RU и EN.

    python3 speech.py script.md
    python3 speech.py script.md --target 5:00        # сколько слов не хватает до нужной длины или лишние
    python3 speech.py script.md --wpm 120-140        # свой темп: число или вилка слов в минуту
    python3 speech.py script.md --voice voice.md --json

Считаются только слова, которые произносятся. Не считаются: заголовки (строки с "#" и строки,
целиком выделенные **жирным**), строки целиком в квадратных скобках ([НА ЭКРАНЕ: ...],
[ON SCREEN: ...]) и любые пометки в квадратных скобках внутри строки, таймкоды вида (0:00-0:15),
маркеры списков и цитат. Число цифрами считается за одно слово.

Заголовки делят сценарий на блоки. Для каждого блока печатается число слов, вилка длительности
и таймкод от начала видео - чтобы хронометраж в сценарии был посчитан, а не придуман.

Темп по умолчанию: 120-140 слов в минуту для русской речи в кадре, 140-160 для английской (язык
определяется по тексту). Вилка честнее одного числа: темп у людей разный.

Замечания "x": слова из раздела "Слова, которые я не использую" в voice.md (с блоком и строкой) и
блоки длиннее 90 секунд речи без единой пометки [НА ЭКРАНЕ: ...] - зрителю не на что смотреть.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import guard, usage, die, parse_args, read_text, banned_words, find_banned, duration, fmt_ts

PACE = {"ru": (120, 140), "en": (140, 160)}
LANG = {"ru": "русский", "en": "английский"}
NO_VISUAL = 90                                   # секунд речи без картинки, после которых блок помечается
WORD = re.compile(r"[a-zа-яё0-9]+(?:[-'’][a-zа-яё0-9]+)*", re.I)
HEAD = re.compile(r"^(?:#{1,6}\s+(.+?)\s*#*|\*\*([^*]+)\*\*[:.]?\s*(?:\([^)]*\))?)$")
CLOCK = r"\d{1,2}:\d{2}(?::\d{2})?"
TIME = re.compile(r"\(?\s*" + CLOCK + r"(?:\s*[-–—]\s*" + CLOCK + r")?\s*\)?")
NOTE = re.compile(r"\[[^\]]*\]")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
VISUAL = re.compile(r"\[\s*(на экране|экран|on screen|screen|b-roll)", re.I)

def parse(text):
    """Текст сценария -> блоки [{name, words, lines, visual}]; блоки без произносимых слов выпадают."""
    blocks, fence = [], False
    def block(name):
        blocks.append({"name": name, "words": 0, "lines": [], "visual": False}); return blocks[-1]
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```"): fence = not fence; continue
        if fence or not line or re.match(r"^([-*_=]\s*){3,}$", line): continue
        m = HEAD.match(line)
        if m:
            name = re.sub(r"[*_`#]", "", TIME.sub(" ", m.group(1) or m.group(2)))
            cur = block(" ".join(name.split()).strip(" .:-–—") or "без названия"); continue
        if cur is None: cur = block("до первого заголовка")
        if VISUAL.search(line): cur["visual"] = True
        s = NOTE.sub(" ", LINK.sub(r"\1", re.sub(r"<!--.*?-->", " ", line)))
        s = re.sub(r"^(>\s*)*(([-*+•]|\d+[.)])\s+)?", "", TIME.sub(" ", s).strip())
        s = " ".join(re.sub(r"[*_`~]", "", s).split())
        n = len(WORD.findall(s))
        if n: cur["words"] += n; cur["lines"].append(s)
    return [b for b in blocks if b["words"]]

def pace(opt, lg):
    if "--wpm" not in opt: return PACE[lg]
    m = re.match(r"^\s*(\d{2,3})(?:\s*[-–—]\s*(\d{2,3}))?\s*$", opt["--wpm"])
    if not m: die(f"--wpm: нужно число слов в минуту или вилка (130 или 120-140), а получено '{opt['--wpm']}'")
    lo, hi = sorted((int(m.group(1)), int(m.group(2) or m.group(1))))
    if lo < 60: die("--wpm: медленнее 60 слов в минуту не говорят")
    return lo, hi

def span(a, b):
    """Вилка времени без повтора, когда границы совпали."""
    return fmt_ts(a) if fmt_ts(a) == fmt_ts(b) else f"{fmt_ts(a)}-{fmt_ts(b)}"

def fit(words, target, lo, hi):
    """Сравнение с нужной длиной. Разница округляется до десятка: точнее темп речи не известен."""
    need = (int(round(target * lo / 60.0)), int(round(target * hi / 60.0)))
    tens = lambda x: int(round(x / 10.0)) * 10
    if words < need[0]: kind, a, b = "short", tens(need[0] - words), tens(need[1] - words)
    elif words > need[1]: kind, a, b = "long", tens(words - need[1]), tens(words - need[0])
    else: kind, a, b = "fits", 0, 0
    if kind != "fits" and b == 0: kind = "fits"
    rng = (f"{a}-{b}" if a and a != b else str(b))
    msg = {"short": f"до {fmt_ts(target)} не хватает {rng} слов",
           "long": f"для {fmt_ts(target)} лишние {rng} слов",
           "fits": f"длина попадает в {fmt_ts(target)}"}[kind]
    return {"seconds": target, "need_words": list(need), "verdict": kind, "delta_words": [a, b], "msg": msg}

def main():
    pos, opt = parse_args(sys.argv[1:], flags=("--json",), options=("--wpm", "--target", "--voice"))
    if not sys.argv[1:]: usage(__doc__)
    if not pos: die("не задан файл сценария: python3 speech.py script.md")
    path = pos[0]
    if not os.path.isfile(path): die(f"нет файла: {path}")
    text = read_text(path)
    if not text.strip(): die(f"файл пустой: {path}")
    blocks = parse(text)
    if not blocks: die(f"в {path} нет текста для произнесения - только заголовки и пометки")
    spoken = " ".join(l for b in blocks for l in b["lines"])
    lg = "ru" if len(re.findall(r"[а-яё]", spoken, re.I)) >= len(re.findall(r"[a-z]", spoken, re.I)) else "en"
    lo, hi = pace(opt, lg); mid = (lo + hi) / 2.0
    target = duration(opt, "--target")
    voice = opt.get("--voice")
    if voice and not os.path.isfile(voice):
        print(f"предупреждение: нет файла {voice} - слова не из голоса автора не проверялись", file=sys.stderr)
    banned = banned_words(voice)
    total, at, bad = sum(b["words"] for b in blocks), 0.0, []
    for b in blocks:
        b["seconds"] = [int(round(b["words"] * 60.0 / hi)), int(round(b["words"] * 60.0 / lo))]
        b["start"], at = int(round(at)), at + b["words"] * 60.0 / mid
        b["end"] = int(round(at))
        for l in b["lines"]:
            bad += [{"word": w, "block": b["name"], "line": l} for w in find_banned(l, banned)]
    blind = [b for b in blocks if not b["visual"] and b["words"] * 60.0 / mid > NO_VISUAL]
    out = {"file": path, "lang": lg, "wpm": [lo, hi], "words": total,
           "seconds": [int(round(total * 60.0 / hi)), int(round(total * 60.0 / lo))],
           "blocks": [{k: b[k] for k in ("name", "words", "seconds", "start", "end", "visual")} for b in blocks],
           "target": fit(total, target, lo, hi) if target else None, "banned": bad,
           "voice_checked": bool(banned), "no_visual": [b["name"] for b in blind]}
    if "--json" in opt: print(json.dumps(out, ensure_ascii=False, indent=1)); return
    rate = str(lo) if lo == hi else f"{lo}-{hi}"
    print(f"\n  {os.path.basename(path)}: {LANG[lg]} текст, темп {rate} слов в минуту"
          + ("" if "--wpm" in opt else " (по умолчанию)"))
    print(f"\n    {'блок':<30} {'слов':>5}  {'вслух':<11} таймкод при {mid:g} сл/мин")
    for b in blocks:
        name = b["name"] if len(b["name"]) <= 30 else b["name"][:29] + "…"
        print(f"    {name:<30} {b['words']:>5}  {span(*b['seconds']):<11} {fmt_ts(b['start'])}-{fmt_ts(b['end'])}")
    print(f"    {'всего':<30} {total:>5}  {span(*out['seconds'])}")
    print()
    if out["target"]:
        t = out["target"]
        print(f"    {'ok' if t['verdict'] == 'fits' else 'x '} {t['msg']} (при темпе {rate} на {fmt_ts(target)} нужно слов: "
              + (str(t["need_words"][0]) if lo == hi else f"{t['need_words'][0]}-{t['need_words'][1]}") + ")")
    for x in bad: print(f"    x  слово не из голоса автора: {x['word']} - блок \"{x['block']}\": {x['line'][:110]}")
    if banned and not bad: print("    ok слов не из голоса автора нет")
    for b in blind:
        print(f"    x  блок \"{b['name']}\": около {fmt_ts(b['words'] * 60.0 / mid)} речи без пометки [НА ЭКРАНЕ: ...] - "
              "зрителю не на что смотреть; добавь картинку или раздели блок")
    if not blind: print(f"    ok блоков длиннее {NO_VISUAL} с без пометки [НА ЭКРАНЕ: ...] нет")
    print()

if __name__ == "__main__":
    guard(main)
