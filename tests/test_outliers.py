#!/usr/bin/env python3
"""Проверка outliers.py и fetch.py: текстовый список "название — просмотры", числа "как пишут люди"
в json, блок "насколько этому верить", fetch без yt-dlp и fetch --json. Без сети.
Запуск: python3 tests/test_outliers.py"""
import json, os, stat, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S, D = os.path.join(ROOT, "scripts"), os.path.join(ROOT, "tests", "data")
fails = []
tmp = tempfile.TemporaryDirectory()
t = lambda name: os.path.join(tmp.name, name)
ENV = dict(os.environ, YT_STUDIO_HOME=t("home"), PYTHONIOENCODING="utf-8")

def raw(tool, *args, env=None):
    return subprocess.run([sys.executable, os.path.join(S, tool)] + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=dict(ENV, **(env or {})))

def run(*args, code=0):
    p = raw("outliers.py", *args)
    if p.returncode != code: fails.append(f"outliers.py {args}: код {p.returncode}, ждали {code}\n{p.stderr}")
    return p.stdout if code == 0 else p.stderr

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

def write(name, text):
    with open(t(name), "w", encoding="utf-8") as f: f.write(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False))
    return t(name)

js = lambda *args: json.loads(run(*(args + ("--json",))))
has = lambda r, word: any(word in c for c in r["caveats"])
HIT = "Как я пробежал марафон без подготовки"

# 1. текстовый формат: все разделители, последний разделитель, числа руками проверены:
#    остальные шесть - 36, 38, 40, 41, 45, 52 тыс -> медиана (40+41)/2 = 40 500; 310 000 / 40 500 = 7.65
f = write("run.txt", "# Бег с нуля\n"
                     "Как я пробежал марафон без подготовки — 310 тыс;\n"
                     "\n"
                     "5 ошибок новичка в беге - 41 тыс\n"
                     "Кроссовки - обзор - пара за 3 000 - 36 тыс\n"
                     "План на 10 км\t38к\n"
                     "Пульс: зоны; 40 000\n"
                     "Растяжка после бега – 45,0 тыс.\n"
                     "- Бег зимой — 52000 просмотров\n")
r = js(f, "--min", "0")
by = {o["title"]: o for o in r["outliers"]}
check("текст: 7 строк - 7 видео, пустая строка пропущена", r["videos"] == 7 and len(by) == 7)
check("текст: база 40 500 и кратное 7.65 у хита", by[HIT]["baseline"] == 40500 and by[HIT]["multiple"] == 7.65 and by[HIT]["views"] == 310000)
check("текст: разделители ' — ', ' - ', ' – ', таб и ';'", [by[k]["views"] for k in ("5 ошибок новичка в беге", "План на 10 км", "Пульс: зоны", "Растяжка после бега", "Бег зимой")]
      == [41000, 38000, 40000, 45000, 52000])
check("текст: берётся последний разделитель, тире в названии остаётся", by.get("Кроссовки - обзор - пара за 3 000", {}).get("views") == 36000)
check("текст: канал из строки '# ...'", {o["channel"] for o in r["outliers"]} == {"Бег с нуля"})
check("текст: у хита остальные ниже порога 1.5", [o["title"] for o in js(f)["outliers"]] == [HIT])
out = run(f)
check("текст: обычный вывод с кратным и базой", "7.65x" in out and "40,500" in out and "насколько этому верить" in out)

body = "\n".join(f"Видео {i} — {v}" for i, v in enumerate([10, 11, 12, 13, 14, 50]))
f2 = write("Мой канал.txt", body)
check("текст: без '#' и --channel канал - имя файла", {o["channel"] for o in js(f2, "--min", "0")["outliers"]} == {"Мой канал"})
check("текст: --channel задаёт имя канала", {o["channel"] for o in js(f2, "--min", "0", "--channel", "Имя из ключа")["outliers"]} == {"Имя из ключа"})
check("текст: строка '# ...' сильнее --channel", {o["channel"] for o in js(f, "--min", "0", "--channel", "Другое")["outliers"]} == {"Бег с нуля"})
f3 = write("two.txt", "# А\n" + body + "\n# Б\n" + body.replace("Видео", "Ролик") + "\n#shorts утро — 5 тыс\n")
r = js(f3, "--min", "0")
check("текст: несколько каналов в одном файле, '#хэштег ... — число' - это видео", {o["channel"] for o in r["outliers"]} == {"А", "Б"} and r["videos"] == 13)

# [short]: Shorts считаются отдельно от длинных
f4 = write("mix.txt", "# Микс\n" + body + "\n" + "\n".join(f"Шортс {i} — {v} тыс [short]" for i, v in enumerate([100, 110, 120, 130, 900]))
           + "\nЕщё шортс; 125 тыс [Шортс]\n")
r = js(f4, "--min", "0")
sh = [o for o in r["outliers"] if o["format"] == "short"]
top = max(sh, key=lambda o: o["multiple"])
check("текст: [short] и [шортс] помечают Shorts", len(sh) == 6 and all(o["title"].lower().endswith(("шортс", "шортс 0", "шортс 1", "шортс 2", "шортс 3", "шортс 4")) for o in sh))
check("текст: Shorts сравниваются между собой (900 при базе 120 = 7.5)", top["views"] == 900000 and top["baseline"] == 120000 and top["multiple"] == 7.5)
check("текст: длинные не смешаны с Shorts (50 при базе 12 = 4.17)", any(o["format"] == "long" and o["multiple"] == 4.17 for o in r["outliers"]))
check("текст: маркер не попадает в название", not any("[" in o["title"] for o in r["outliers"]))

# кривая строка: файл и номер строки, одна строка, без трейсбека
fb = write("bad.txt", "# Канал\nНормальное — 10 тыс\n\nПросто строка без числа\n")
err = run(fb, code=1)
check("текст: непонятная строка - ошибка с файлом и номером строки", "bad.txt" in err and "строка 4" in err and len(err.strip().splitlines()) == 1 and "Traceback" not in err)
err = run(write("bad2.txt", "Название — много\n"), code=1)
check("текст: просмотры не число - та же ошибка со строкой 1", "строка 1" in err and "не json" not in err)

# 2. json: числа как пишут люди, понятные ошибки
views = ["310 тыс", "41 тыс", "36к", 38000, "40 000", "45,0 тыс.", 52000.0]
titles = [HIT, "5 ошибок", "Кроссовки", "План", "Пульс", "Растяжка", "Зима"]
fj = write("hand.json", [{"channel": "Бег json", "title": a, "views": v} for a, v in zip(titles, views)])
r = js(fj)
check("json: '310 тыс' и '36к' во views читаются, числа те же", len(r["outliers"]) == 1 and r["outliers"][0]["baseline"] == 40500 and r["outliers"][0]["multiple"] == 7.65)
fj2 = write("nochan.json", [{"title": a, "views": v} for a, v in zip(titles, views)])
check("json: без channel канал из --channel или имени файла", js(fj2)["outliers"][0]["channel"] == "nochan" and js(fj2, "--channel", "Ключ")["outliers"][0]["channel"] == "Ключ")
for bad in ("много", [1], True):
    err = run(write("badviews.json", [{"channel": "К", "title": "Видео с кривыми просмотрами", "views": bad}]), code=1)
    check(f"json: views={bad!r} - ошибка называет видео, а не 'не json'", "Видео с кривыми просмотрами" in err and "не json" not in err
          and "badviews.json" in err and "Traceback" not in err and "внутренняя" not in err)
err = run(write("syntax.json", "{не json"), code=1)
check("json: синтаксическая ошибка по-прежнему 'не json'", "не json" in err and "syntax.json" in err)
r = js(os.path.join(D, "chanA.json"), os.path.join(D, "chanB.json"), "--min", "2")
check("дамп yt-dlp: как раньше, один выброс", len(r["outliers"]) == 1 and r["outliers"][0]["multiple"] > 8)

# смешанный запуск: текст + свой json + дамп yt-dlp
r = js(f, fj, os.path.join(D, "chanA.json"), "--min", "2")
check("смешанный вход: txt и json в одном запуске", {"Бег с нуля", "Бег json"} <= {o["channel"] for o in r["outliers"]} and r["videos"] > 14)

# 3. оговорки: каждая только тогда, когда относится к данным
def chan(name, n, **extra):
    return [dict({"channel": name, "title": f"{name} {i}", "views": 1000 + 10 * i}, **extra) for i in range(n)]
full = lambda name, n: chan(name, n, duration=600, date="20240101")
r = js(write("c_all.json", full("А", 10) + full("Б", 10) + full("В", 10)), "--min", "0")
check("оговорки: полные данные (3 канала по 10, даты, длительность) - список пуст", r["caveats"] == [])
out = run(t("c_all.json"))
check("оговорки: при пустом списке блок не печатается", "насколько этому верить" not in out)
r = js(write("c_small.json", full("А", 9) + full("Б", 10) + full("В", 10)), "--min", "0")
check("оговорки: только 'мало видео' при группе из 9, назван канал", len(r["caveats"]) == 1 and "мало видео" in r["caveats"][0] and "А (длинные) - 9" in r["caveats"][0] and "Б (" not in r["caveats"][0])
r = js(write("c_dates.json", chan("А", 10, duration=600) + chan("Б", 10, duration=600) + chan("В", 10, duration=600)), "--min", "0")
check("оговорки: только 'нет дат'", len(r["caveats"]) == 1 and "нет дат" in r["caveats"][0])
r = js(write("c_dates2.json", full("А", 10) + full("Б", 10) + chan("В", 10, duration=600)), "--min", "0")
check("оговорки: даты есть не у всех - сказано, у скольких нет", len(r["caveats"]) == 1 and "у 10 видео из 30 нет даты" in r["caveats"][0])
r = js(write("c_dur.json", full("А", 10) + full("Б", 10) + chan("В", 10, date="20240101")), "--min", "0")
check("оговорки: только 'нет длительности', с числом видео", len(r["caveats"]) == 1 and "у 10 видео нет ни длительности" in r["caveats"][0])
r = js(write("c_url.json", full("А", 10) + full("Б", 10) + chan("В", 10, date="20240101", url="https://www.youtube.com/shorts/x")), "--min", "0")
check("оговорки: ссылка на /shorts/ заменяет длительность", r["caveats"] == [] and sum(o["format"] == "short" for o in r["outliers"]) == 10)
r = js(write("c_flag.json", full("А", 10) + full("Б", 10) + chan("В", 10, date="20240101", short=False)), "--min", "0")
check("оговорки: явное \"short\": false - формат известен", r["caveats"] == [])
r = js(write("c_two.json", full("А", 10) + full("Б", 10)), "--min", "0")
check("оговорки: только 'каналов: 2'", len(r["caveats"]) == 1 and "каналов в расчёте: 2" in r["caveats"][0])
r = js(f)
check("оговорки: текстовый список одного канала - все четыре", len(r["caveats"]) == 4 and has(r, "мало видео") and has(r, "нет дат")
      and has(r, "у 7 видео нет ни длительности") and has(r, "каналов в расчёте: 1"))
r = js(f4, "--min", "0")
check("оговорки: в тексте с пометками [short] формат считается известным", not has(r, "длительности"))
r = js(write("c_thin.json", full("А", 10) + full("Б", 10) + full("В", 10) + full("Г", 3)), "--min", "0")
check("оговорки: пропущенная группа (<5) идёт в skipped_thin, а не в 'мало видео'", r["caveats"] == [] and r["skipped_thin"] == [["Г", "длинные", 3]])

# 4. --recent: первые записи файла считаются последними видео
r = js(write("recent.txt", "\n".join(f"Новое {i} — 100" for i in range(5)) + "\n" + "\n".join(f"Старое {i} — 9000" for i in range(5))), "--recent", "5", "--min", "0")
check("--recent берёт первые строки файла (порядок от новых к старым)", len(r["outliers"]) == 5 and all(o["title"].startswith("Новое") for o in r["outliers"]))
doc = raw("outliers.py").stdout
check("справка: сказано про порядок от новых к старым и текстовый формат", "ОТ НОВЫХ К СТАРЫМ" in doc and "название — просмотры" in doc and "--channel" in doc)

# 5-6. fetch.py
try:
    import yt_dlp  # noqa: F401
    have_module = True
except ImportError:
    have_module = False
if have_module:
    print("  skip fetch без yt-dlp: модуль yt_dlp установлен, отсутствие не изобразить")
else:
    for kind, url in (("channel", "https://www.youtube.com/@x"), ("captions", "https://youtu.be/abc")):
        p = raw("fetch.py", kind, url, "--out", t("no-" + kind), env={"PATH": t("нет-такой-папки")})
        check(f"fetch {kind} без yt-dlp: код 3, инструкция, папка --out не создана",
              p.returncode == 3 and "yt-dlp не установлен" in p.stderr and "Traceback" not in p.stderr and not os.path.exists(t("no-" + kind)))
    p = raw("fetch.py", "channel", "https://www.youtube.com/@x", "--out", t("no-json"), "--json", env={"PATH": t("нет-такой-папки")})
    check("fetch --json без yt-dlp: тот же код 3, stdout пуст", p.returncode == 3 and not p.stdout.strip() and not os.path.exists(t("no-json")))

if os.name == "nt":
    print("  skip fetch --json: подставной yt-dlp - sh-скрипт, на Windows не запускается")
else:
    binp = t("bin"); os.makedirs(binp)
    stub = os.path.join(binp, "yt-dlp")
    with open(stub, "w") as fh:
        fh.write('#!/bin/sh\ncase "$*" in\n'
                 '  *--flat-playlist*) echo \'{"channel":"Стаб","entries":[]}\' ;;\n'
                 '  *) out=""; while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n'
                 '     echo "[download] шум yt-dlp"\n'
                 '     printf "WEBVTT\\n\\n00:00.000 --> 00:02.000\\nпривет\\n" > "$(dirname "$out")/abc.ru.vtt" ;;\nesac\n')
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
    env = {"PATH": binp + os.pathsep + os.environ["PATH"]}
    p = raw("fetch.py", "channel", "https://www.youtube.com/@stub/videos", "--out", t("ch"), "--json", env=env)
    try: r = json.loads(p.stdout)
    except ValueError: r = {}
    check("fetch channel --json: kind и два сохранённых файла", p.returncode == 0 and r.get("kind") == "channel" and len(r.get("saved", [])) == 2
          and all(os.path.exists(x) for x in r["saved"]) and sorted(os.path.basename(x) for x in r["saved"]) == ["stub_shorts.json", "stub_videos.json"])
    p = raw("fetch.py", "captions", "https://youtu.be/abc", "--out", t("cap"), "--json", env=env)
    try: r = json.loads(p.stdout)
    except ValueError: r = {}
    check("fetch captions --json: в stdout только json, вывод yt-dlp ушёл в stderr", p.returncode == 0 and r.get("kind") == "captions"
          and r.get("saved") == [os.path.join(t("cap"), "abc.ru.vtt")] and "шум yt-dlp" in p.stderr)
    p = raw("fetch.py", "captions", "https://youtu.be/abc", "--out", t("cap2"), env=env)
    check("fetch без --json: прежний текстовый вывод", p.returncode == 0 and "субтитры сохранены" in p.stdout and "abc.ru.vtt" in p.stdout)
    p = raw("fetch.py", "channel", "https://www.youtube.com/@stub", "--out", t("ch2"), env=env)
    check("fetch channel без --json: прежний текстовый вывод", p.returncode == 0 and "список канала сохранён" in p.stdout)

tmp.cleanup()
print()
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)}")
    for x in fails: print("  -", x)
    sys.exit(1)
print("все проверки пройдены")
