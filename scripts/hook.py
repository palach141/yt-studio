#!/usr/bin/env python3
"""hook.py - линтер хука (первых фраз видео), RU и EN.

    python3 hook.py --hook "одна фраза"
    python3 hook.py hooks.txt                       # по одному хуку на строку
    python3 hook.py hooks.txt --voice voice.md --json

Три вида пометок: "x" - механическая ошибка (снимает баллы), "ok" - проверка пройдена, "?" - то,
о чём инструмент судить не может и что надо оценить самому (на балл не влияет).

Что считается ошибкой: штамп или приветствие в начале, представление себя, просьба подписаться,
пустые усилители ("невероятный"), три и больше слов-паразитов, слова не из голоса автора
(voice.md), хук, который сам отвечает на свой вопрос, длина - больше, чем помещается в первые
15 секунд (около 38 слов по-русски при 130 словах в минуту, около 42 по-английски при 150), или
меньше пяти слов. Язык определяется для каждого хука отдельно.

ЧЕГО ЭТО НЕ УМЕЕТ. Проверка считает слова, а не смысл. Балл - счётчик ошибок, а не мера качества:
бессмысленная фраза без штампов получит 100, как и хорошая. Несколько хуков без ошибок - обычное
дело, выбирать между ними надо по смыслу: что хук обещает, какой вопрос открывает, подтверждает ли
заголовок. При равном балле порядок - как в файле.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import (guard, usage, NUM_WORDS, tokens, VAGUE, CLICHE, parse_args, read_text, banned_words, find_banned,
                   classify, load_formulas, die)

# вес проблемы: сколько баллов она снимает
WEIGHT = {"штамп": 25, "представление": 20, "подписка": 20, "голос": 15, "вода": 15, "длинно": 15,
          "коротко": 15, "сам-ответ": 15, "паразиты": 10}
PACE = {"ru": (130, 38), "en": (150, 42)}       # темп речи в кадре, слов в минуту, и предел слов в хуке
HOOK_SEC, MIN_WORDS, FILLER_MAX = 15, 5, 3
# площадки пишутся с заглавной, но конкретикой видео не являются
PLATFORMS = ("youtube", "ютуб", "shorts", "шортс", "tiktok", "тикток", "instagram", "reels", "telegram", "vk")
WORD = re.compile(r"[a-zа-яё0-9]+(?:[-'’][a-zа-яё0-9]+)*", re.I)

GREET = [r"^\W*(привет|здравствуйте|добрый (день|вечер)|доброе утро|hi|hello|hey)\b"]
# представление и просьба о подписке проверяются отдельно, чтобы одна фраза не штрафовалась дважды
OWN = re.compile(r"зовут|name is|подписаться|subscribe|лайк")
# имя узнаётся по заглавной букве, поэтому регистр отключён только у слов вокруг него
INTRO = re.compile(r"(?i:\bменя зовут\b|\bвы на канале\b|\bна (мо[её]м|нашем|этом) канале\b|\bmy name is\b|"
                   r"\b(on|to) (my|our|this|the) channel\b)|^\W*[Яя]\s+[А-ЯЁ][а-яё]+|"
                   r"(?i:\b(с вами|на связи|I'm|I am|this is))\s+[A-ZА-ЯЁ][a-zа-яё]+\b")
ASK = re.compile(r"\b(подпиш(ись|итесь)|подписаться|подписывай(ся|тесь)|(по)?(ставь|жми)(те)? (лайк|колокольчик)|"
                 r"лайк и|subscribe|hit the (bell|like)|smash (that|the) like|leave a like)\b", re.I)
FILLER = re.compile(r"\b(basically|actually|literally|really|very|honestly|kind of|sort of|you know|i mean|"
                    r"вообще|в общем|в принципе|собственно|буквально|реально|очень|короче|типа|как бы|как-то|"
                    r"так сказать|просто|немного|кстати|ну)\b")
OPENER = re.compile(r"\?|(?:^|[.!?…]\s+)\W*(почему|зачем|как|что|сколько|угадай|why|how|what|guess)\b")
CLOSED = re.compile(r"\b(because|so that|which means|that's why|потому что|поэтому|а значит|то есть|дело в том)\b")
ORDINAL = re.compile(r"\b((втор|четверт|пят|шест|седьм|восьм|девят|десят|[а-я]+дцат|сороков|сот)"
                     r"(ый|ой|ая|ое|ого|ому|ым|ом|ую|ые|ых|ыми)|трет(ий|ья|ье|ьего|ьему|ьей|ью|ьем|ьим|ьи|ьих)|"
                     r"second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b")
YOU = re.compile(r"\b(you|your|yours|you're|you've|you'll|yourself|ты|тебя|тебе|тобой|тво(й|я|е|и|их|ей|ю|им|его|ему)|"
                 r"вы|вас|вам|вами|ваш(а|е|и|их|ей|у|им|его|ему)?)\b")
IMPER = re.compile(r"\b(слушай|смотри|посмотри|глянь|проверь|скажи|представь|подумай|вспомни|запомни|попробуй|"
                   r"возьми|открой|сделай|перестань|остановись|подожди|стой|угадай|забудь|запиши|посчитай|найди|"
                   r"ответь|признайся|держи)(те)?\b|(?:^|[.!?…]\s+)\W*(stop|look|listen|imagine|check|try|watch|"
                   r"tell|think|remember|take|open|ask|guess|picture|don't|forget|pick|count|notice)\b")
VERB2 = re.compile(r"\b[а-я]{2,}(ешь|ишь|ешься|ишься)\b|\b[а-я]{3,}(ете|ите|етесь|итесь)\b")
# существительные и частицы с теми же окончаниями, что у глаголов второго лица
NOT_VERB = set("лишь брешь плешь тишь интернете планете бюджете ответе совете свете цвете газете монете ракете "
               "кабинете университете комитете пакете билете сюжете диете кредите орбите лимите аппетите элите "
               "защите визите транзите паритете приоритете авторитете".split())
# вопрос, начатый глаголом в прошедшем времени без подлежащего ("Бросил бегать?"), обращён к зрителю
PAST_Q = re.compile(r"^\W*([а-я]{3,}(л|ла|ли|лся|лась|лись))\b(?![^.!?…]*\b(я|мы|он|она|они|оно)\b)[^.!?…]*\?")

def lang(t):
    return "ru" if len(re.findall(r"[а-яё]", t, re.I)) >= len(re.findall(r"[a-z]", t, re.I)) else "en"

def concrete(t, low):
    """Что конкретного названо: цифра, число словом, порядковое или имя собственное; None, если ничего."""
    if re.search(r"\d", t): return "число"
    num = next((w for w in tokens(t) if w in NUM_WORDS), None)
    if num: return f"число словом ({num})"
    m = ORDINAL.search(low)
    if m: return f"порядковое числительное ({m.group(0)})"
    # имя собственное: слово с заглавной не в начале предложения и не целиком капсом
    start = True
    for raw in t.split():
        w = raw.strip("«»\"'()[]:;,.!?…—–-")
        if (not start and len(w) > 1 and w[0].isupper() and not w.isupper() and not re.match(r"I\b", w)
                and not w.lower().startswith(PLATFORMS)): return f"имя ({w})"
        start = raw[-1] in ".!?…:" or not w
    return None

def address(low):
    """Каким словом назван зритель: местоимение, повелительное наклонение или глагол второго лица."""
    m = YOU.search(low) or IMPER.search(low)
    if m: return m.group(0).strip(" .!?…")
    for m in VERB2.finditer(low):
        if m.group(0) not in NOT_VERB: return m.group(0)
    for s in re.split(r"(?<=[.!?…])\s+", low):
        m = PAST_Q.match(s)
        if m and m.group(1) not in ("если", "или"): return m.group(1)
    return None

def check(hook, banned, formulas):
    t = hook.strip(); low = t.lower().replace("ё", "е")
    lg = lang(t); wpm, limit = PACE[lg]
    n = len(WORD.findall(t)); sec = int(round(n * 60.0 / wpm))
    issues, good, notes = [], [], []
    cl = [m.group(0) for m in (re.search(p, low) for p in CLICHE + GREET if not OWN.search(p)) if m]
    cl = [x for x in cl if not any(x != y and x in y for y in cl)]       # "hey" внутри "hey guys" - один штамп, не два
    if cl: issues.append(("штамп", f"{', '.join(cl)} - с этих слов начинаются тысячи видео; начни с обещания"))
    else: good.append("штампов и приветствий нет")
    if INTRO.search(" ".join(t.split()[:12])):
        issues.append(("представление", "хук начинается с того, кто ты; зрителю сначала нужна причина остаться"))
    if ASK.search(low): issues.append(("подписка", "просьба подписаться или поставить лайк до того, как что-то дано"))
    bad = find_banned(t, banned)
    if bad: issues.append(("голос", f"слова не из твоего голоса (voice.md): {', '.join(bad)}"))
    elif banned: good.append("слов не из твоего голоса нет")
    vague = sorted({w for w in tokens(t) if w in VAGUE})
    if vague: issues.append(("вода", f"{', '.join(vague)} - усилитель без меры; замени на число, имя или факт"))
    fill = FILLER.findall(low)
    if len(fill) >= FILLER_MAX: issues.append(("паразиты", f"слов-паразитов: {len(fill)} ({', '.join(fill)})"))
    q, c = OPENER.search(low), None
    if q: c = CLOSED.search(low, q.end())
    if c: issues.append(("сам-ответ", f'после вопроса идёт "{c.group(0)}" - хук сам закрывает то, что открыл; '
                                      "оставь ответ для видео"))
    if n > limit: issues.append(("длинно", f"слов: {n}, вслух около {sec} с - в первые {HOOK_SEC} с помещается "
                                           f"около {limit}; оставь одну мысль"))
    elif n < MIN_WORDS: issues.append(("коротко", f"слов: {n} - меньше {MIN_WORDS}; обещание в такую фразу не помещается"))
    elif sec > HOOK_SEC: notes.append(f"вслух около {sec} с - на границе {HOOK_SEC} с; прочитай с секундомером")
    else: good.append(f"длина: вслух около {sec} с при {wpm} словах в минуту")
    name, hits = classify(t, formulas)
    if hits:
        phrase = next((f.get("user_phrase") for f in formulas if f["name"] == name), None)
        notes.append(f'формула по словам: "{name}"' + (f" - {phrase}" if phrase else "") + "; так ли это по смыслу, реши сам")
    else: notes.append("слова не совпали ни с одной формулой - это не ошибка; назови сам, что делает хук")
    d = concrete(t, low)
    if d: good.append(f"есть конкретная деталь: {d}")
    else: notes.append("нет числа/имени - проверь, не абстрактно ли")
    a = address(low)
    if a: good.append(f'зритель назван: "{a}"')
    else: notes.append("прямого обращения к зрителю нет - для вопроса из поиска или рассказа о себе это нормально")
    score = max(0, 100 - sum(WEIGHT[k] for k, _ in issues))
    return {"hook": t, "lang": lg, "words": n, "seconds": sec, "score": score, "formula": name,
            "issues": [{"kind": k, "msg": m} for k, m in issues], "good": good, "notes": notes}

def show(r):
    print(f'\n  "{r["hook"]}"')
    k = len(r["issues"])
    print(f"  слов: {r['words']}, вслух около {r['seconds']} с   "
          + (f"механических ошибок: {k}, балл {r['score']}/100" if k else "механических ошибок нет"))
    for i in r["issues"]: print(f"    x  {i['kind']:<15} {i['msg']}")
    for m in r["good"]:   print(f"    ok                 {m}")
    for m in r["notes"]:  print(f"    ?                  {m}")

def hooks(path):
    """Строки файла -> хуки: без пустых строк, заголовков, маркеров списка и кавычек вокруг."""
    out = []
    for l in read_text(path).splitlines():
        l = re.sub(r"^\s*(\d+[.)]|[-*•])\s+", "", l).strip().strip("«»\"“”").strip()
        if l and not l.startswith("#"): out.append(l)
    return out

def main():
    pos, opt = parse_args(sys.argv[1:], flags=("--json",), options=("--hook", "--voice"))
    if not sys.argv[1:]: usage(__doc__)
    if "--hook" in opt and not opt["--hook"].strip(): die("--hook: пустая строка")
    if "--hook" in opt: lines = [opt["--hook"]]
    elif pos:
        if not os.path.isfile(pos[0]): die(f"нет файла: {pos[0]}")
        lines = hooks(pos[0])
        if not lines: die(f"в файле нет хуков: {pos[0]}")
    else: die("не задан текст: нужен файл с хуками (по одному на строку) или --hook \"фраза\"")
    voice = opt.get("--voice")
    if voice and not os.path.isfile(voice):
        print(f"предупреждение: нет файла {voice} - слова не из голоса автора не проверялись", file=sys.stderr)
    banned, formulas = banned_words(voice), load_formulas()
    # равный балл не значит равное качество: при ничьей сохраняем порядок автора
    rows = [r for _, r in sorted(enumerate(check(t, banned, formulas) for t in lines), key=lambda x: (-x[1]["score"], x[0]))]
    if "--json" in opt: print(json.dumps(rows, ensure_ascii=False, indent=1)); return
    for r in rows: show(r)
    if len(rows) > 1:
        clean = len([r for r in rows if not r["issues"]])
        print(f"\n  Хуков без механических ошибок: {clean}. " + ("Проверка между ними не выбирает: выбор - это суждение "
              "о смысле." if clean > 1 else "Это счёт ошибок в словах, а не оценка: силён ли хук - суждение о смысле."))
    print()

if __name__ == "__main__":
    guard(main)
