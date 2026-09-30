#!/usr/bin/env python3
"""Проверка title.py: пары "заголовок || обложка", пометки "?", однокоренные дубли, RU и EN.
Запуск: python3 tests/test_title.py"""
import json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "scripts", "title.py")
fails = []
tmp = tempfile.TemporaryDirectory()
t = lambda name: os.path.join(tmp.name, name)
# пустая домашняя папка: настоящий voice.md автора в проверках не участвует
ENV = dict(os.environ, YT_STUDIO_HOME=t("home"), PYTHONIOENCODING="utf-8")

def run(*args, code=0):
    p = subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=ENV)
    if p.returncode != code: fails.append(f"title.py {args}: код {p.returncode}, ждали {code}\n{p.stderr}")
    return p.stdout

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

def one(title, thumb=None, *extra):
    return json.loads(run("--title", title, *((("--thumb", thumb) if thumb else ()) + extra + ("--json",))))[0]

def write(name, text):
    with open(t(name), "w", encoding="utf-8") as f: f.write(text)
    return t(name)

kinds = lambda r: {i["kind"] for i in r["issues"]}
notes = lambda r: " | ".join(r["notes"])

# 1. число словом
r = one("Три ошибки на обложке, из-за которых нет кликов")
check("число словом считается конкретикой", "нет-конкретики" not in kinds(r) and r["score"] == 100)
check("число словом: мягкая заметка про цифру, без штрафа", "цифрой читается быстрее" in notes(r))
r = one("3 ошибки обложки, которые съедают клики")
check("цифра: заметки про число словом нет", not r["notes"] and not r["issues"])
r = one("Five Thumbnail Mistakes Nobody Fixes")
check("EN: число словом тоже конкретика с заметкой", "нет-конкретики" not in kinds(r) and "five" in notes(r))

# 2. однокоренные дубли и осторожная формулировка
r = one("Три ошибки на обложке, из-за которых нет кликов", "ТАК НЕ КЛИКНУТ")
check("дубль: однокоренная пара кликов/кликнут поймана", "дубль" in kinds(r) and "кликнут" in str(r["issues"]))
r = one("Ошибка в обложке", "ОШИБКИ ОБЛОЖЕК")
check("дубль: другая форма слова по-прежнему ловится", "дубль" in kinds(r))
r = one("Как контент держит зрителя 8 минут", "НУЖЕН КОНТРАСТ")
check("дубль: контент/контраст - не повтор", "дубль" not in kinds(r))
check("нет дубля: сообщение не обещает лишнего", any("однокоренные и синонимы проверь сам" in g for g in r["good"]))

# 3. мобильная лента - под "?", а не под "ok"
long_ok = "Почему ваше видео пролистывают: 3 ошибки на обложке"
r = one(long_ok, "СЕРОЕ ПЯТНО")
check("json: есть список notes рядом с issues и good", isinstance(r.get("notes"), list) and "issues" in r and "good" in r)
check("мобильная лента: видимая часть в notes, не в good",
      '"Почему ваше видео пролистывают: 3 ошибки..."' in notes(r) and not any("мобильн" in g for g in r["good"]))
check("мобильная лента: заметка не снимает баллы", r["score"] == 100 and not r["issues"])
out = run("--title", long_ok)
line = [l for l in out.splitlines() if "в мобильной ленте" in l]
check("текстовый вывод: мобильная строка идёт под '?'", len(line) == 1 and line[0].strip().startswith("?"))
r = one("Короткий заголовок про 3 ошибки")
check("короткий заголовок: мобильной заметки нет", not r["notes"])
r = one("Почему вашу обложку пролистывают все: 3 ошибки")
check("обрыв на числе назван висящим", "обрыв на числе" in notes(r) and '3..."' in notes(r))
r = one("Как набрать просмотры на YouTube без рекламы в 2025")
check("обрыв на предлоге назван висящим", "обрыв на служебном слове" in notes(r))
r = one("Почему обложку видео никто не открывает: разбор 3 ошибок")
check("обрыв на двоеточии назван висящим", "обрыв на знаке препинания" in notes(r))
r = one("Вот что это и как у нас тут было до того, как вышло 2025")
check("меньше двух значимых слов в видимой части - ошибка 'мобильный'", "мобильный" in kinds(r) and "в мобильной ленте видно" in notes(r))

# 4. пары в файле
f = write("pairs.txt", "3 ошибки обложки, которые съедают клики || СЕРОЕ ПЯТНО\n"
                       "\n"
                       "Ошибка в обложке || ОШИБКИ ОБЛОЖЕК\n"
                       "7 правок обложки за вечер\n"
                       "9 правок заголовка за вечер ||\n")
rows = {r["title"]: r for r in json.loads(run(f, "--thumb", "ОБЩАЯ", "--json"))}
check("файл: у каждой строки своя обложка", rows["3 ошибки обложки, которые съедают клики"]["thumb"] == "СЕРОЕ ПЯТНО"
      and rows["Ошибка в обложке"]["thumb"] == "ОШИБКИ ОБЛОЖЕК" and len(rows) == 4)
check("файл: дубль считается по своей обложке", "дубль" in kinds(rows["Ошибка в обложке"]))
check("файл: строка без '||' берёт --thumb", rows["7 правок обложки за вечер"]["thumb"] == "ОБЩАЯ")
check("файл: пустая обложка после '||' - проверка без обложки", rows["9 правок заголовка за вечер"]["thumb"] is None)
rows = json.loads(run(f, "--json"))
check("файл без --thumb: строка без '||' идёт без обложки", [r["thumb"] for r in rows if r["title"].startswith("7")] == [None])
p = subprocess.run([sys.executable, TOOL, write("empty.txt", "\n  \n")], capture_output=True, text=True, encoding="utf-8", env=ENV)
check("файл без заголовков: понятная ошибка", p.returncode == 1 and "Traceback" not in p.stderr and p.stderr.strip())
check("формат '||' описан в справке", "||" in run())

# 5. ничьи
clean = ["5 правок обложки за вечер", "7 правок заголовка за вечер", "9 правок хука за вечер"]
f = write("ties.txt", "\n".join([clean[0], "Лучший секрет обложки", clean[1], clean[2]]) + "\n")
rows = json.loads(run(f, "--json"))
check("ничья: порядок как в файле, слабый - в конце", [r["title"] for r in rows] == clean + ["Лучший секрет обложки"])
out = run(f)
check("несколько чистых: итоговая строка про суждение о смысле", "без механических ошибок: 3" in out and "о смысле" in out)
check("один чистый заголовок: итоговой строки нет", "без механических ошибок" not in run("--title", clean[0])
      and "без механических ошибок" not in run(write("one.txt", clean[0] + "\nЛучший секрет обложки\n")))

# 6. грамматика
t53 = "Как я снял 5 видео и понял 3 вещи про обложки и клики"          # ровно 53 знака: было "53 знаков"
out = run("--title", t53, "--thumb", "СЕРОЕ ПЯТНО") + run(f) \
    + run("--title", "A" * 61) + run("--title", "Б" * 101 + " 1") + run("--title", "ЭТО ОЧЕНЬ ГРОМКИЙ ЗАГОЛОВОК ПРО 3 ВЕЩИ")
check("грамматика: нигде нет 'N знаков' / 'N слов'", len(t53) == 53 and "знаков: 53" in out and not re.search(r"\d+ (знак|слов)", out))

# 7. площадки - не конкретика
r = one("Как набрать просмотры на YouTube без рекламы")
check("YouTube в середине заголовка не считается именем", "нет-конкретики" in kinds(r))
bad = [w for w in ("Ютубе", "Shorts", "Шортс", "TikTok", "Instagram", "Reels", "Telegram", "VK")
       if "нет-конкретики" not in kinds(one("Как набрать просмотры в " + w + " без рекламы"))]
check("остальные площадки тоже не считаются именем", not bad)
r = one("Как набрать просмотры по методу Дудя на YouTube")
check("настоящее имя рядом с площадкой считается", any("Дудя" in g for g in r["good"]))

# 8. слова на обложке
r = one("3 ошибки обложки, которые съедают клики", "ТАК НЕ НАДО ДЕЛАТЬ")
check("обложка: 4 слова с частицами - ошибка с объяснением",
      any(i["kind"] == "обложка" and "слов на обложке: 4, включая частицы и предлоги" in i["msg"] for i in r["issues"]))
r = one("3 ошибки обложки, которые съедают клики", "ТАК НЕ НАДО")
check("обложка: три слова проходят", "обложка" not in kinds(r))

# английский
r = one("5 Thumbnail Mistakes That Kill Your Views", "NOBODY CLICKS")
check("EN: чистая пара без замечаний", not r["issues"] and r["score"] == 100)
r = one("5 Thumbnail Mistakes That Kill Your Clicks", "NOBODY CLICKS")
check("EN: повтор слова на обложке пойман", "дубль" in kinds(r))
r = one("The Ultimate Secret Thumbnail Mistake", "THUMBNAILS FAIL")
check("EN: вода и дубль в другой форме пойманы", {"вода", "дубль"} <= kinds(r))
r = one("Why Nobody Clicks On Videos You Made For Them In 3 Months")
check("EN: обрыв на служебном слове", "обрыв на служебном слове" in notes(r))

# voice.md через --voice
v = write("voice.md", "# Голос\n\n## Слова, которые я не использую\n- лайфхак\n")
r = one("3 лайфхака для обложки", None, "--voice", v)
check("--voice: запрещённое слово поймано", "голос" in kinds(r))
check("без voice.md: проверки голоса нет", "голос" not in kinds(one("3 лайфхака для обложки")))

tmp.cleanup()
print("\n" + ("ВСЁ ПРОШЛО" if not fails else f"ПРОВАЛОВ: {len(fails)}\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
