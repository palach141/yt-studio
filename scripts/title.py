#!/usr/bin/env python3
"""title.py - линтер пары "заголовок + текст на обложке", RU и EN.

    python3 title.py --title "..." --thumb "ТРИ СЛОВА"
    python3 title.py titles.txt                    # по паре на строку: заголовок || ТЕКСТ ОБЛОЖКИ
    python3 title.py titles.txt --thumb "..."      # --thumb - для строк без "||"
    python3 title.py --title "..." --json

Единица проверки - пара, а не заголовок. Обложка, которая повторяет заголовок, тратит половину
кликабельной площади впустую. Поэтому в файле у каждой строки своя обложка: "заголовок || ТЕКСТ".
Строка без "||" берёт --thumb, если он задан; строка "заголовок ||" проверяется без обложки.

Три вида пометок: "x" - механическая ошибка (снимает баллы), "ok" - проверка пройдена, "?" - то,
о чём инструмент судить не может и что надо посмотреть глазами (на балл не влияет).

Балл - это счётчик ошибок, а не мера качества: несколько заголовков со 100/100 - обычное дело,
и выбирать между ними надо по смыслу. При равном балле порядок - как в файле.

Длина: YouTube режет заголовок примерно на 60 знаках в поиске на десктопе и примерно на 40 в
мобильной ленте (зависит от устройства и ширины букв - это ориентиры, не точные границы). Жёсткий
предел - 100 знаков.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import (guard, usage, tokens, stem, same_root, STOP, VAGUE, NUM_WORDS, parse_args, read_text,
                   banned_words, find_banned, die)

DESKTOP, MOBILE, HARD, THUMB_MAX = 60, 40, 100, 3
# вес проблемы: сколько баллов она снимает
WEIGHT = {"длина": 25, "длинно": 10, "мобильный": 12, "крик": 12, "вода": 12, "нет-конкретики": 10,
          "начало": 10, "знаки": 8, "дубль": 18, "обложка": 10, "голос": 15}
# площадки пишутся с заглавной, но конкретикой видео не являются
PLATFORMS = ("youtube", "ютуб", "shorts", "шортс", "tiktok", "тикток", "instagram", "reels", "telegram", "vk")
# слова, на которых обрыв в мобильной ленте оставляет фразу висеть
DANGLE = set("""и а но или что как чтобы если когда не ни в во на с со к о об от до за из по у для про без при
над под через нет который которая которые которых ваш ваша ваше ваши твой твоя твое твои мой моя мое мои
the a an of for to in on and or but with at by from that than if when which your my our their""".split())

def concrete(t):
    """(что нашлось, заметка) - цифра, число словом или имя собственное; (None, None), если ничего."""
    if re.search(r"\d", t): return "число", None
    num = next((w for w in tokens(t) if w in NUM_WORDS), None)
    if num: return f"число словом ({num})", f'число словом ("{num}") - цифрой читается быстрее'
    # имя собственное: слово с заглавной не в начале и не целиком капсом
    words = t.split()
    for prev, w in zip(words, words[1:]):
        # слово после точки, вопроса, двоеточия или тире - начало фразы, а не имя ("Ты", "Вот")
        if prev[-1:] in ".!?:…—–-": continue
        w = w.strip("«»\"'()[]:,.!?—-")
        if len(w) > 1 and w[0].isupper() and not w.isupper() and not w.lower().startswith(PLATFORMS) and w.lower() not in STOP:
            return f"имя ({w})", None
    return None, None

def mobile_head(t):
    """Видимая в мобильной ленте часть: до последнего целого слова в пределах MOBILE знаков."""
    head = t[:MOBILE]
    return head if t[MOBILE] == " " else head.rsplit(" ", 1)[0]

def dangling(head):
    last = (tokens(head) or [""])[-1]
    if head[-1] in ":;,-—–(«\"": return "знаке препинания"
    if last.isdigit() or last in NUM_WORDS: return "числе"
    if last in DANGLE: return "служебном слове"
    return None

def check(title, thumb=None, banned=()):
    t = title.strip(); n = len(t)
    issues, good, notes = [], [], []
    if n > HARD: issues.append(("длина", f"знаков: {n} - жёсткий предел YouTube {HARD}"))
    elif n > DESKTOP: issues.append(("длинно", f"знаков: {n} - поиск на десктопе режет около {DESKTOP}"))
    else: good.append(f"знаков: {n}, помещается в {DESKTOP}")
    if n > MOBILE:
        head = mobile_head(t)
        if len([w for w in tokens(head) if w not in STOP and len(w) > 2]) < 2:
            issues.append(("мобильный", "в видимой части мобильной ленты меньше двух значимых слов - "
                                        "предмет видео не помещается"))
        d = dangling(head)
        notes.append(f'в мобильной ленте видно: "{head}..." - ' + (f"обрыв на {d}, конец висит; переставь слова "
                     "так, чтобы предмет шёл раньше" if d else "проверь глазами, что предмет видео выжил"))
    caps = [w for w in t.split() if len(re.sub(r"\W", "", w)) > 2 and w.isupper()]
    if len(caps) > 2: issues.append(("крик", f"слов капсом: {len(caps)} - больше двух читается как спам"))
    vague = sorted({w for w in tokens(t) if w in VAGUE})
    if vague: issues.append(("вода", f"{', '.join(vague)} - замени на число, имя или дату"))
    c, note = concrete(t)
    if c: good.append(f"есть конкретика: {c}")
    else: issues.append(("нет-конкретики", "нет ни числа, ни имени - самая надёжная одиночная правка"))
    if note: notes.append(note)
    if not [w for w in tokens(t)[:3] if w not in STOP]:
        issues.append(("начало", "первые три слова - служебные; вынеси предмет вперёд"))
    if re.search(r"[!?]{2,}|\.{4,}", t): issues.append(("знаки", "несколько '!' или '?' подряд читаются как кликбейт"))
    bad = find_banned(t + " " + (thumb or ""), banned)
    if bad: issues.append(("голос", f"слова не из твоего голоса (voice.md): {', '.join(bad)}"))
    if thumb:
        tw = [w for w in tokens(t) if w not in STOP]
        shared = []
        for w in tokens(thumb):
            pair = next((x for x in tw if stem(x) == stem(w) or same_root(x, w)), None)
            if w in STOP or pair is None: continue
            s = w if pair == w else f"{w} (в заголовке: {pair})"
            if s not in shared: shared.append(s)
        if shared: issues.append(("дубль", f"обложка повторяет заголовок: {', '.join(shared)} - "
                                           "пусть говорит то, чего в заголовке нет"))
        else: good.append("обложка не повторяет слова заголовка (однокоренные и синонимы проверь сам)")
        k = len(tokens(thumb))
        if k > THUMB_MAX: issues.append(("обложка", f"слов на обложке: {k}, включая частицы и предлоги - "
                                                    f"в ленте читается не больше {THUMB_MAX}"))
    score = max(0, min(100, 100 - sum(WEIGHT[k] for k, _ in issues)))
    return {"title": t, "thumb": thumb, "chars": n, "score": score,
            "issues": [{"kind": k, "msg": m} for k, m in issues], "good": good, "notes": notes}

def show(r):
    print(f'\n  "{r["title"]}"' + (f'   + обложка "{r["thumb"]}"' if r["thumb"] else ""))
    print(f"  знаков: {r['chars']}   балл {r['score']}/100")
    for i in r["issues"]: print(f"    x  {i['kind']:<15} {i['msg']}")
    for m in r["good"]:   print(f"    ok                 {m}")
    for m in r["notes"]:  print(f"    ?                  {m}")

def pairs(path, thumb):
    """Строки файла -> [(заголовок, обложка)]. "заголовок || ТЕКСТ" несёт свою обложку."""
    out = []
    for l in read_text(path).splitlines():
        title, sep, own = l.partition("||")
        if title.strip(): out.append((title, own.strip() or None) if sep else (title, thumb))
    return out

def main():
    pos, opt = parse_args(sys.argv[1:], flags=("--json",), options=("--title", "--thumb", "--voice"))
    banned, thumb = banned_words(opt.get("--voice")), opt.get("--thumb")
    if "--title" in opt and not opt["--title"].strip(): die("--title: пустая строка")
    if "--title" in opt: rows = [check(opt["--title"], thumb, banned)]
    elif pos and os.path.exists(pos[0]):
        rows = [check(t, th, banned) for t, th in pairs(pos[0], thumb)]
        if not rows: die(f"в файле нет заголовков: {pos[0]}")
    elif not sys.argv[1:]: usage(__doc__)
    else: die("не задан текст: нужен файл с вариантами или параметр, см. запуск без аргументов")
    # равный балл не значит равное качество: при ничьей сохраняем порядок автора
    rows = [r for _, r in sorted(enumerate(rows), key=lambda x: (-x[1]["score"], x[0]))]
    if "--json" in opt: print(json.dumps(rows, ensure_ascii=False, indent=1)); return
    for r in rows: show(r)
    clean = len([r for r in rows if not r["issues"]])
    if clean > 1: print(f"\n  Заголовков без механических ошибок: {clean}. Линтер между ними не выбирает: "
                        "дальше это суждение о смысле, а не о балле.")
    print()

if __name__ == "__main__":
    guard(main)
