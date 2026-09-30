#!/usr/bin/env python3
"""Проверка retention.py: разбор хука, окна текста, округление, склон, форматы файлов.
Запуск: python3 tests/test_retention.py"""
import json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL, D = os.path.join(ROOT, "scripts", "retention.py"), os.path.join(ROOT, "tests", "data")
fails = []

def raw(*args):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")

def run(*args):
    p = raw(*args)
    if p.returncode != 0: fails.append(f"retention.py {args}: код {p.returncode}\n{p.stderr}")
    return p.stdout

def js(*args):
    try: return json.loads(run(*(args + ("--json",))))
    except ValueError: fails.append(f"retention.py {args}: не json"); return {}

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

def friendly(p):
    return p.returncode not in (0, 70) and p.stderr.strip() and "Traceback" not in p.stderr

csvf, srt = os.path.join(D, "retention.csv"), os.path.join(D, "talk.srt")
args = (csvf, "--duration", "1:22", "--transcript", srt)
txt, r = run(*args), js(*args)
first = r.get("hook_first") or {}
lines = [l for l in txt.splitlines() if l.strip()]

# 1. разбор хука
check("хук: первые 5 секунд отделены от остатка окна", first.get("lost") == 15.3 and r["hook_rest"] == 7.6 and r["hook_leak"] == 22.9)
check("хук: части в сумме дают весь хук", abs(first.get("lost", 0) + r["hook_rest"] - r["hook_leak"]) < 0.05)
check("хук: концентрация в начале названа словами", r["hook_front_loaded"] and "больше половины - в первые 5 секунд: это первая фраза и первый кадр" in txt)
check("хук: первая фраза из транскрипта - только первые 5 секунд", first.get("said") == "Если у тебя меньше тысячи подписчиков, это видео для тебя." and first["said"] in txt)
check("хук: в тексте те же числа, что в json", "-22.9 п. за 30 секунд" in txt and "-15.3 п. за первые 5 секунд" in txt and "-7.6 п. за остаток" in txt)

# 2. окно текста для всплеска и обрыва
bump, cliff = r["bumps"][0], r["cliffs"][0]
check("всплеск: текст в точке и после неё, а не до", bump["said"].startswith("Обрыв на графике") and "Экспортируй" in bump["said"] and "Дальше удержание" not in bump["said"])
check("обрыв: текст перед ним", "Ну вот, короче." in cliff["said"] and "Проверяй обложку" not in cliff["said"])

# 3. позиции и округление
check("позиция округляется до ближайшей секунды (56.6 -> 0:57)", bump["at"] == "0:57" and bump["at_seconds"] == 56.6 and "0:57" in txt and "0:56" not in txt)
check("половина округляется вверх, одинаково в тексте и json", cliff["lost"] == 6.3 and bump["gain"] == 1.8 and r["end"] == 57.3
      and "-6.3 п." in txt and "+1.8 п." in txt and "57.3%" in txt)

# 4. склон
check("склон: всего за середину, без обрывов и всплесков", r["slide_total"] == 15.4 and "-15.4 п. за середину (0:30 - 1:22" in txt)
check("хук + обрывы - всплески + склон = вся потеря", abs(r["hook_leak"] + cliff["lost"] - bump["gain"] + r["slide_total"] - (r["start"] - r["end"])) < 0.15)
check("склон: на коротком видео нет пересчёта в минуту", r["slide_per_minute"] is None and r["short_video"]
      and "на коротком видео пересчёт в минуту не показателен" in txt and "в минуту" not in txt.replace("пересчёт в минуту не показателен", ""))
lng = js(csvf, "--duration", "10:00"); ltxt = run(csvf, "--duration", "10:00")
check("склон: на длинном видео - всего и в минуту", lng["slide_per_minute"] == 2.5 and lng["slide_total"] == 23.3
      and "-23.3 п. за середину (0:30 - 10:00" in ltxt and "это -2.5 п. в минуту" in ltxt and "не показателен" not in ltxt)
check("норм и оценок в выводе нет", not any(w in (txt + ltxt).lower() for w in ("хорошо", "плохо", "норма:", "в норме", "средн. по youtube")))

# 5-6. столбец и шаг данных
check("первая строка: взятый столбец и шаг данных", 'столбец: "Absolute audience retention (%)"' in lines[0] and "шаг данных: 0.8 с" in lines[0]
      and r["column"].startswith("Absolute") and r["step_seconds"] == 0.8)
check("шаг 6 с: первый срез хука сдвигается на первую точку", (lng.get("hook_first") or {}).get("seconds") == 6.0 and "за первые 6 с" in ltxt and lng["step_seconds"] == 6.0)
nod = js(csvf); ntxt = run(csvf, "--transcript", srt)
check("без длины: хук в процентах видео, разбор по первым 5%", nod["hook_window"] == "первые 10% видео" and nod["hook_first"]["window"] == "первые 5% видео"
      and nod["hook_first"]["lost"] == 15.0 and "длина видео не задана" in ntxt and nod["cliffs"][0].get("said") is None)

with tempfile.TemporaryDirectory() as tmp:
    def make(name, text, enc="utf-8"):
        p = os.path.join(tmp, name)
        with open(p, "w", encoding=enc) as f: f.write(text)
        return p
    curve = [100 - 0.4 * i for i in range(101)]                                   # ровная кривая 100 -> 60

    p = make("nohead.csv", "\n".join(f"{i},{y:.2f}" for i, y in enumerate(curve)))
    o = run(p, "--duration", "10:00")
    check("без заголовка столбец не называется", "столбец" not in o and js(p)["column"] is None)
    check("ровная кривая: обрывов и всплесков нет", js(p)["cliffs"] == [] and js(p)["bumps"] == [] and "нет - потери ровные" in o)
    check("размазанный хук не называется концентрацией", not js(p, "--duration", "10:00")["hook_front_loaded"] and "больше половины" not in o)

    p = make("rel_first.csv", "Position;Relative retention;Absolute retention\n" + "\n".join(f"{i};50;{y:.2f}" for i, y in enumerate(curve)))
    check("абсолютный столбец находится по заголовку, даже третьим", js(p)["column"] == "Absolute retention" and js(p)["end"] == 60.0)

    p = make("ru.csv", "Позиция\tУдержание\n" + "\n".join(f"{i}\t{str(round(y, 1)).replace('.', ',')}" for i, y in enumerate(curve)), enc="utf-16")
    o = js(p)
    check("табуляция, десятичные запятые, UTF-16, русский заголовок", o["points"] == 101 and o["end"] == 60.0 and o["column"] == "Удержание")

    p = make("semi.csv", "\n".join(f"{i * 0.5:.1f};{y:.2f}".replace(".", ",") for i, y in enumerate(curve)))
    o = js(p, "--duration", "50")
    check("точка с запятой и десятичные запятые в обоих столбцах", o["points"] == 101 and o["axis"] == "seconds" and o["start"] == 100.0 and o["end"] == 60.0)

    p = make("frac.csv", "elapsedVideoTimeRatio,audienceWatchRatio,relativeRetentionPerformance\n" + "\n".join(f"{i / 100:.2f},{y / 100:.4f},0.5" for i, y in enumerate(curve)))
    o = js(p, "--duration", "10:00")
    check("доли 0..1 в позиции и в удержании читаются как проценты", o["axis"] == "percent" and o["start"] == 100.0 and o["end"] == 60.0
          and o["step_seconds"] == 6.0 and o["column"] == "audienceWatchRatio")

    p = make("secs.csv", "\n".join(f"{i * 6},{y:.2f}" for i, y in enumerate(curve)))
    o = js(p)
    check("ось в секундах: длина берётся из файла", o["axis"] == "seconds" and o["duration"] == 600 and o["hook_window"] == "30 секунд" and o["step_seconds"] == 6.0)
    p = make("secs80.csv", "\n".join(f"{i},{100 - 0.5 * i:.2f}" for i in range(81)))
    o = js(p, "--duration", "1:20")
    check("ось в секундах у видео короче 100 с отличается от процентов по --duration", o["axis"] == "seconds" and o["hook_first"]["seconds"] == 5.0 and o["hook_first"]["lost"] == 2.5)
    o = run(p)
    check("без длины неполная ось считается процентами с предупреждением", "Если это секунды - дай --duration" in o)

    pts = [(0, 0), (0, 15), (0, 30), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]
    p = make("clock.csv", "\n".join(f"{m}:{s:02d}; {100 - 4 * i}" for i, (m, s) in enumerate(pts)))
    o = js(p); t = run(p)
    check("позиции м:сс: ось в секундах, шаг 60 с", o["axis"] == "seconds" and o["points"] == 9 and o["step_seconds"] == 60.0 and o["hook_leak"] == 8.0)
    check("редкие точки: первые 15 с вместо 5, оценка хука помечена", o["hook_first"]["seconds"] == 15.0 and o["hook_approx"] and "оценка" in t)
    p = make("clock_short.csv", "\n".join(f"0:{i * 5:02d}, {100 - 3 * i}" for i in range(13)))
    o = js(p)
    check("позиции м:сс у видео на минуту не путаются с процентами", o["axis"] == "seconds" and o["duration"] == 60 and o["hook_window"] == "30 секунд" and o["hook_leak"] == 18.0)
    p = make("sparse.csv", "\n".join(f"{m}:00, {100 - 5 * m}" for m in range(10)))
    o = js(p); t = run(p)
    check("точки раз в минуту: хук не раскладывается, об этом сказано", o["hook_first"] is None and o["hook_rest"] is None and "слишком редкие" in t)

    p = make("few.csv", "a,b\n" + "\n".join(f"{i},{100 - i}" for i in range(7)))
    q = raw(p)
    check("меньше 8 точек: понятная ошибка", friendly(q) and "меньше 8" in q.stderr)
    check("нет файла и кривая длина: понятная ошибка", friendly(raw(os.path.join(tmp, "нет.csv"))) and friendly(raw(csvf, "--duration", "абв")))
    check("кривой транскрипт: без трейсбека", "Traceback" not in raw(csvf, "--duration", "1:22", "--transcript", make("bad.srt", "")).stderr)

    p = make("shorts.csv", "Секунда,Удержание\n" + "\n".join(f"{i},{(100 - 10 * i) if i <= 2 else (81 - 0.5 * i):.1f}" for i in range(41)))
    o = js(p, "--duration", "40"); t = run(p, "--duration", "40")
    check("Shorts: окно хука - 20% видео, первый срез - половина окна", o["axis"] == "seconds" and o["hook_window"] == "первые 8 с" and o["hook_first"]["seconds"] == 4.0
          and o["hook_first"]["lost"] == 21.0 and o["hook_rest"] == 2.0 and o["hook_front_loaded"] and "в первые 4 с" in t)
    p = make("shorts_pct.csv", "\n".join(f"{i},{y:.2f}" for i, y in enumerate(curve)))
    o = js(p, "--duration", "0:20")
    check("Shorts с осью в процентах: окно в секундах", o["hook_window"] == "первые 4 с" and o["hook_first"]["seconds"] == 2.0 and o["step_seconds"] == 0.2 and o["short_video"])

    ys = [100, 108, 112, 109, 104, 99] + [98 - 0.4 * i for i in range(95)]
    p = make("over.csv", "\n".join(f"{i},{y:.2f}" for i, y in enumerate(ys)))
    o = js(p, "--duration", "10:00"); t = run(p, "--duration", "10:00")
    check("начало выше 100%: не доли, рост печатается плюсом, пояснение есть", o["start"] == 100.0 and o["peak"] == 112.0 and o["hook_first"]["lost"] == -8.0
          and "+8.0 п. за первые 6 с" in t and "выше 100" in t and not o["hook_front_loaded"])
    p = make("over_frac.csv", "\n".join(f"{i},{y / 100:.4f}" for i, y in enumerate(ys)))
    check("начало выше 100% в долях (1.12) читается как 112%", js(p)["peak"] == 112.0)

    # обрезка текста по границе слова
    # у каждой реплики свои слова: одинаковые подряд загрузчик считает повтором автосубтитров
    seg = lambda k: " ".join("%s%02d" % (k, i) for i in range(60))
    tr = make("long.srt", "1\n00:00:00,000 --> 00:00:04,000\n" + seg("начало") + "\n\n2\n00:04:55,000 --> 00:04:59,000\n" + seg("перед")
              + "\n\n3\n00:06:30,000 --> 00:06:34,000\n" + seg("после") + "\n")
    ys = [100 - 0.2 * i for i in range(101)]
    for i in range(51, 101): ys[i] -= 8                                           # обрыв на 50% = 5:00
    for i in range(66, 101): ys[i] += 3                                           # всплеск на 65% = 6:30
    p = make("cut.csv", "\n".join(f"{i},{y:.2f}" for i, y in enumerate(ys)))
    o = js(p, "--duration", "10:00", "--transcript", tr)
    b, c, h = o["bumps"][0]["said"], o["cliffs"][0]["said"], o["hook_first"]["said"]
    whole = lambda s: all(re.match(r"(начало|перед|после)\d\d$", w) for w in s.strip("…").split())
    check("обрезка текста: по границе слова, с многоточием, не длиннее 161 знака", b.startswith("после00") and b.endswith("…") and whole(b) and len(b) <= 161 and h.endswith("…") and whole(h))
    check("обрезка перед обрывом оставляет конец фразы", c.startswith("…") and c.endswith("перед59") and whole(c))
    check("несколько находок: обрыв 5:00 и всплеск 6:30", o["cliffs"][0]["at"] == "5:00" and o["cliffs"][0]["lost"] == 8.2 and o["bumps"][0]["at"] == "6:30" and o["bumps"][0]["gain"] == 2.8)
    check("сумма частей сходится и здесь", abs(o["hook_leak"] + o["cliffs"][0]["lost"] - o["bumps"][0]["gain"] + o["slide_total"] - (o["start"] - o["end"])) < 0.15)

ref = open(os.path.join(ROOT, "references", "retention.md"), encoding="utf-8").read()
check("retention.md: команда, опубликованное видео, исключение, 'из каждых 100'", "python3 ${CLAUDE_SKILL_DIR}/scripts/retention.py " in ref
      and "cuts.py" in ref and "на следующее видео" in ref and "Исключение" in ref and "из каждых 100 зрителей" in ref)
doc = raw().stdout + raw().stderr
check("справка описывает разбор хука и окна текста", "первые 5 секунд" in doc and "ПОСЛЕ" in doc and "Traceback" not in doc)

print("\n" + ("ВСЁ ПРОШЛО" if not fails else f"ПРОВАЛОВ: {len(fails)}\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
