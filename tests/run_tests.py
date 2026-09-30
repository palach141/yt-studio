#!/usr/bin/env python3
"""Проверка инструментов yt-studio на данных из tests/data. Запуск: python3 tests/run_tests.py"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S, D = os.path.join(ROOT, "scripts"), os.path.join(ROOT, "tests", "data")
fails = []
# личные файлы автора тесты не читают и не трогают: домашняя папка подменяется пустой временной
_home = tempfile.mkdtemp(); os.environ["YT_STUDIO_HOME"] = _home

def run(tool, *args, code=0):
    p = subprocess.run([sys.executable, os.path.join(S, tool)] + list(args), capture_output=True, text=True)
    if p.returncode != code: fails.append(f"{tool} {args}: код {p.returncode}, ждали {code}\n{p.stderr}")
    return p.stdout

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

d = lambda f: os.path.join(D, f)

r = json.loads(run("hook.py", "--hook", "Всем привет, сегодня я расскажу про невероятный лайфхак", "--voice", d("voice.md"), "--json"))[0]
check("хук: штамп и запрещённое слово из voice.md пойманы", {"штамп", "голос"} <= {i["kind"] for i in r["issues"]} and r["score"] < 100)
r = json.loads(run("hook.py", "--hook", "Если у тебя меньше 1000 подписчиков, ты теряешь клики на обложке. Почему?", "--json"))[0]
check("хук: русский текст оценивается, формула найдена", not r["issues"] and r["lang"] == "ru" and r["formula"] != "не определена")

r = json.loads(run("title.py", "--title", "Как сделать лучший заголовок для видео на YouTube и не потерять зрителей в ленте",
                   "--thumb", "ЛУЧШИЙ ЗАГОЛОВОК ДЛЯ ВИДЕО", "--json"))[0]
kinds = {i["kind"] for i in r["issues"]}
check("заголовок: длина, вода, дубль с обложкой, длинная обложка", {"длинно", "вода", "дубль", "обложка"} <= kinds)
r = json.loads(run("title.py", "--title", "3 ошибки обложки, которые съедают клики", "--thumb", "СЕРОЕ ПЯТНО", "--json"))[0]
check("заголовок: чистая пара проходит без замечаний", not r["issues"])
r = json.loads(run("title.py", "--title", "Ошибка в обложке", "--thumb", "ОШИБКИ ОБЛОЖЕК", "--json"))[0]
check("заголовок: дубль ловится и в другой форме слова", any(i["kind"] == "дубль" for i in r["issues"]))

r = json.loads(run("cuts.py", d("talk.srt"), "--json"))
k = [c["kind"] for c in r["cuts"]]
check("рез: пауза, вода и дубль найдены в srt", {"ПАУЗА", "ВОДА", "ДУБЛЬ"} <= set(k))
check("рез: пересечения не считаются дважды", abs(r["duration"] - r["removed"] - sum(b - a for a, b in r["keep"])) < 0.2)
r = json.loads(run("cuts.py", d("words.json"), "--json"))
check("рез: таймкоды по словам - пауза внутри и слово-паразит", r["level"] == "слова" and len(r["cuts"]) == 2)
r = json.loads(run("cuts.py", d("auto.vtt"), "--json"))
check("рез: автосубтитры YouTube читаются без повторов строк", r["level"].startswith("слова") and r["duration"] < 6)
with tempfile.TemporaryDirectory() as tmp:
    edl = os.path.join(tmp, "cut.edl"); run("cuts.py", d("talk.srt"), "--edl", edl, "--fps", "25")
    check("рез: EDL записан", "FCM: NON-DROP FRAME" in open(edl).read())
    j = os.path.join(tmp, "j.jsonl")
    for i in range(1, 5):
        run("journal.py", "add", "--title", f"Видео {i}", "--formula", "Цифра" if i > 2 else "Ошибка", "--file", j)
        run("journal.py", "result", str(i), "--views", str(i * 1000), "--file", j)
    check("журнал: отчёт по формулам", "Цифра" in run("journal.py", "report", "--file", j))

r = json.loads(run("chapters.py", d("talk.srt"), "--target", "5", "--json"))
check("главы: черновик валиден и начинается с 0:00", r["valid"] and r["chapters"][0]["start"] == 0)
check("главы: вывод одинаков от запуска к запуску", r == json.loads(run("chapters.py", d("talk.srt"), "--target", "5", "--json")))
run("chapters.py", "--check", d("chapters_ok.txt"), "--duration", "1:21")
run("chapters.py", "--check", d("chapters_bad.txt"), code=2)
check("главы: --check пропускает годный блок и отклоняет негодный", True)

r = json.loads(run("retention.py", d("retention.csv"), "--duration", "1:21", "--transcript", d("talk.srt"), "--json"))
check("удержание: обрыв на 40% найден и подписан текстом", r["cliffs"] and r["cliffs"][0]["from"] == 39 and r["cliffs"][0].get("said"))
check("удержание: всплеск найден", r["bumps"] and r["bumps"][0]["from"] == 69)

r = json.loads(run("outliers.py", d("chanA.json"), d("chanB.json"), "--min", "2", "--json"))
check("выбросы: найден один, Shorts не смешаны с длинными", len(r["outliers"]) == 1 and r["outliers"][0]["multiple"] > 8)
check("выбросы: канал с одним видео пропущен с объяснением", r["skipped_thin"] and r["skipped_thin"][0][0] == "Канал Б")


# ---------------------------------------------------------------- устойчивость и упаковка
import glob, py_compile, re, shutil, stat

def raw(tool, *args, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, os.path.join(S, tool)] + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=e)

tools = sorted(os.path.basename(f) for f in glob.glob(os.path.join(S, "*.py")) if not f.endswith("ytlib.py"))
ok = True
for f in glob.glob(os.path.join(S, "*.py")):
    try: compile(open(f, encoding="utf-8").read(), f, "exec")
    except SyntaxError: ok = False
check("все скрипты компилируются", ok)
bad = [t for t in tools if t != "doctor.py" and (raw(t).returncode != 0 or raw(t).stderr.strip() or t[:-3] not in raw(t).stdout)]
check("запуск без аргументов печатает справку, а не падает", not bad)

with tempfile.TemporaryDirectory() as tmp:
    t = lambda name: os.path.join(tmp, name)
    open(t("empty.srt"), "w").close()
    open(t("bin.srt"), "wb").write(bytes(range(256)) * 20)
    open(t("text.srt"), "w", encoding="utf-8").write("просто текст без таймкодов\n")
    open(t("bad.json"), "w").write("{не json")
    open(t("odd.json"), "w").write('{"segments": "строка", "x": 1}')
    open(t("few.csv"), "w").write("a,b\n1,2\n")
    cases = [("cuts.py", t("empty.srt")), ("cuts.py", t("bin.srt")), ("cuts.py", t("text.srt")), ("cuts.py", t("bad.json")),
             ("cuts.py", t("odd.json")), ("cuts.py", t("нет-такого.srt")), ("chapters.py", t("empty.srt")),
             ("chapters.py", "--check", t("нет.txt")), ("retention.py", t("few.csv")), ("retention.py", t("bin.srt")),
             ("retention.py", d("retention.csv"), "--duration", "абв"), ("outliers.py", t("bad.json")),
             ("outliers.py", t("odd.json")), ("cuts.py", d("talk.srt"), "--floor", "быстро"),
             ("cuts.py", d("talk.srt"), "--неизвестный"), ("hook.py", "--hook", ""), ("title.py", "--title", " "),
             ("journal.py", "result", "99", "--views", "1", "--file", t("j.jsonl")), ("fetch.py", "captions", "не-ссылка")]
    bad = []
    for c in cases:
        p = raw(*c)
        if p.returncode == 0 or "Traceback" in p.stderr or not p.stderr.strip() or p.returncode == 70: bad.append((c, p.returncode, p.stderr[:200]))
    check(f"кривой вход ({len(cases)} случаев): понятная ошибка, без трейсбека", not bad)
    for b in bad: print("      ", b)

    src = open(d("talk.srt"), encoding="utf-8").read()
    open(t("cp1251.srt"), "wb").write(src.replace("\n", "\r\n").encode("cp1251"))
    a, b = json.loads(run("cuts.py", d("talk.srt"), "--json")), json.loads(run("cuts.py", t("cp1251.srt"), "--json"))
    check("srt в Windows-1251 с CRLF читается так же, как UTF-8", a["cuts"] == b["cuts"])
    open(t("bom.srt"), "w", encoding="utf-16").write(src)
    check("srt в UTF-16 читается", json.loads(run("cuts.py", t("bom.srt"), "--json"))["cuts"] == a["cuts"])
    json.dump({"text": "x", "words": [{"word": "Раз", "start": 0.0, "end": 0.3}, {"word": "два", "start": 1.5, "end": 1.9}]},
              open(t("openai.json"), "w"), ensure_ascii=False)
    r = json.loads(run("cuts.py", t("openai.json"), "--json"))
    check("json со словами на верхнем уровне (OpenAI API) читается", r["level"] == "слова" and len(r["cuts"]) == 1)
    open(t("points.csv"), "w", encoding="utf-8").write("\n".join(f"{m}:{s:02d}; {100 - 4 * i}" for i, (m, s) in enumerate([(0, 0), (0, 15), (0, 30), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0)])))
    r = json.loads(run("retention.py", t("points.csv"), "--json"))
    check("удержание: точки, снятые с графика вручную (мм:сс; процент)", r["axis"] == "seconds" and r["points"] == 9)

    # doctor и журнал - в изолированной домашней папке
    home = {"YT_STUDIO_HOME": t("home")}
    st = json.loads(raw("doctor.py", "--json", env=home).stdout)
    check("doctor: готов, voice.md отсутствует", st["ready"] and st["voice"] == "missing")
    st = json.loads(raw("doctor.py", "--init", "--json", env=home).stdout)
    check("doctor --init: создаёт шаблон voice.md", st["voice"] == "template" and os.path.exists(os.path.join(t("home"), "voice.md")))
    open(os.path.join(t("home"), "voice.md"), "a", encoding="utf-8").write("\n## Слова, которые я не использую\n- погнали\n")
    raw("doctor.py", "--init", env=home)
    st = json.loads(raw("doctor.py", "--json", env=home).stdout)
    check("doctor --init: заполненный voice.md не перезаписывает", st["voice"] == "filled" and st["banned_words"] == 1)
    r = json.loads(raw("hook.py", "--hook", "Ну что, погнали разбирать обложку", "--json", env=home).stdout)[0]
    check("voice.md из домашней папки подхватывается без --voice", any(i["kind"] == "голос" and "погнали" in i["msg"] for i in r["issues"]))
    raw("journal.py", "add", "--title", "Тест", env=home)
    check("журнал пишется в домашнюю папку", os.path.exists(os.path.join(t("home"), "journal.jsonl")))

    # fetch.py с подставным yt-dlp: проверяем, какие аргументы он получит и что делается с результатом
    if os.name != "nt":
        binp = t("bin"); os.makedirs(binp)
        stub = os.path.join(binp, "yt-dlp")
        open(stub, "w").write('#!/bin/sh\necho "$@" >> "$STUB_LOG"\ncase "$*" in\n'
                              '  *--flat-playlist*) echo \'{"channel":"Стаб","entries":[]}\' ;;\n'
                              '  *) out=""; while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n'
                              '     printf "WEBVTT\\n\\n00:00.000 --> 00:02.000\\nпривет\\n" > "$(dirname "$out")/abc.ru.vtt" ;;\nesac\n')
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
        env = {"PATH": binp + os.pathsep + os.environ["PATH"], "STUB_LOG": t("log")}
        p1 = raw("fetch.py", "captions", "https://youtu.be/abc", "--out", t("cap"), env=env)
        p2 = raw("fetch.py", "channel", "https://www.youtube.com/@stub/videos", "--out", t("ch"), env=env)
        log = open(t("log")).read()
        check("fetch captions: субтитры без видео, файл найден", p1.returncode == 0 and "--skip-download" in log and os.path.exists(os.path.join(t("cap"), "abc.ru.vtt")))
        check("fetch channel: обе вкладки, файлы сохранены", p2.returncode == 0 and "@stub/videos" in log and "@stub/shorts" in log and len(os.listdir(t("ch"))) == 2)
        # без yt-dlp: понятная инструкция и код 3 (если yt-dlp не стоит как модуль Python)
        p = raw("fetch.py", "channel", "https://www.youtube.com/@x", env={"PATH": "/nonexistent"})
        check("fetch без yt-dlp: инструкция по установке", p.returncode in (2, 3) and "Traceback" not in p.stderr)

        # install.sh в подставную папку настроек
        cfg = t("cfg")
        p = subprocess.run(["sh", os.path.join(ROOT, "install.sh")], capture_output=True, text=True,
                           env=dict(os.environ, CLAUDE_CONFIG_DIR=cfg, YT_STUDIO_HOME=t("home2")))
        dest = os.path.join(cfg, "skills", "yt-studio")
        check("install.sh: ставит скилл и создаёт voice.md", p.returncode == 0 and os.path.exists(os.path.join(dest, "SKILL.md"))
              and os.path.exists(os.path.join(t("home2"), "voice.md")) and not os.path.exists(os.path.join(dest, "tests")))
        p = subprocess.run([sys.executable, os.path.join(dest, "scripts", "title.py"), "--title", "3 ошибки обложки", "--json"], capture_output=True, text=True)
        check("установленная копия работает", p.returncode == 0)
        open(os.path.join(t("home2"), "voice.md"), "a").write("мои правки")
        subprocess.run(["sh", os.path.join(ROOT, "install.sh")], capture_output=True, env=dict(os.environ, CLAUDE_CONFIG_DIR=cfg, YT_STUDIO_HOME=t("home2")))
        check("повторная установка не трогает voice.md", "мои правки" in open(os.path.join(t("home2"), "voice.md")).read())
        subprocess.run(["sh", os.path.join(ROOT, "install.sh"), "--uninstall"], capture_output=True, env=dict(os.environ, CLAUDE_CONFIG_DIR=cfg))
        check("удаление убирает скилл и оставляет личные данные", not os.path.exists(dest) and os.path.exists(os.path.join(t("home2"), "voice.md")))

# SKILL.md и данные
skill = open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8").read()
fm = skill.split("---")[1]
keys = set(re.findall(r"^([a-z-]+):", fm, re.M))
desc = " ".join(x.strip() for x in re.search(r"description: >-\n(.*?)\n[a-z-]+:", fm, re.S).group(1).splitlines())
check("SKILL.md: только поля спецификации Agent Skills, описание до 1024 знаков",
      keys <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"} and len(desc) <= 1024
      and "<" not in desc and re.search(r"^name: yt-studio$", fm, re.M))
docs = skill + "".join(open(f, encoding="utf-8").read() for f in glob.glob(os.path.join(ROOT, "references", "*.md")))
missing = [x for x in set(re.findall(r"references/[\w-]+\.md|scripts/\w+\.py|data/\w+\.json|templates/\w+\.md|(?<![\w/])\w+\.py(?![\w])", docs))
           if not (os.path.exists(os.path.join(ROOT, x)) or os.path.exists(os.path.join(S, x)))]
check("все файлы, упомянутые в инструкциях, существуют", not missing)
if missing: print("      ", missing)
flags_ok = True
for tool, flag in set(re.findall(r"scripts/(\w+\.py)[^\n`]*?(--[a-z-]+)", docs)):
    if flag not in open(os.path.join(S, tool), encoding="utf-8").read(): flags_ok = False; print("       нет флага", tool, flag)
check("все флаги, упомянутые в инструкциях, есть в инструментах", flags_ok)
sys.path.insert(0, S)
from ytlib import load_formulas, classify
forms = load_formulas()
wrong = [(f["name"], classify(f["example"], forms)[0]) for f in forms if classify(f["example"], forms)[0] != f["name"]]
check(f"каждая из {len(forms)} формул узнаёт собственный пример", not wrong)
for w in wrong: print("      ", w)
for name in ("plugin.json", "marketplace.json"):
    json.load(open(os.path.join(ROOT, ".claude-plugin", name), encoding="utf-8"))
check("манифесты плагина - валидный json", True)

# отдельные наборы проверок по инструментам
for f in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
    p = subprocess.run([sys.executable, f], capture_output=True, text=True, encoding="utf-8", errors="replace")
    n = sum(1 for l in p.stdout.splitlines() if l.startswith("  ok"))
    check(f"{os.path.basename(f)}: {n} проверок", p.returncode == 0)
    if p.returncode: print("\n".join("      " + l for l in p.stdout.splitlines() if "FAIL" in l) + p.stderr[-400:])

print("\n" + ("ВСЁ ПРОШЛО" if not fails else f"ПРОВАЛОВ: {len(fails)}\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
