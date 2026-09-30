#!/usr/bin/env python3
"""Проверка journal.py: форматы чисел и дат, русская запись чисел, пороги отчёта, формулы, edit,
--json у всех команд, целость файла. Запуск: python3 tests/test_journal.py"""
import datetime, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "scripts", "journal.py")
fails = []
tmp = tempfile.TemporaryDirectory()
t = lambda name: os.path.join(tmp.name, name)
# пустая домашняя папка: настоящий журнал автора в проверках не участвует
ENV = dict(os.environ, YT_STUDIO_HOME=t("home"), PYTHONIOENCODING="utf-8")

def raw(*args):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=ENV)

def run(*args, code=0):
    p = raw(*args)
    if p.returncode != code: fails.append(f"journal.py {args}: код {p.returncode}, ждали {code}\n{p.stderr}")
    return p.stdout

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

def rejected(*args):
    """Отказ - это код 1 и одна строка в stderr, без трейсбека."""
    p = raw(*args)
    ok = p.returncode == 1 and len(p.stderr.strip().splitlines()) == 1 and "Traceback" not in p.stderr
    return p.stderr.strip() if ok else ""

def rows(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

def journal(name, n, formula=None, **extra):
    """Журнал из n видео с результатами 1000, 2000, ..."""
    path = t(name)
    for i in range(1, n + 1):
        args = ["add", "--title", f"Видео номер {i}", "--views", str(i * 1000), "--file", path]
        if formula: args += ["--formula", formula(i)]
        run(*args)
    return path

# 1. числа: как их пишут люди
j = t("nums.jsonl")
run("add", "--title", "Почему обложку пролистывают", "--thumb", "СЕРОЕ ПЯТНО", "--file", j)
for text, want in (("8400", 8400), ("8 400", 8400), ("8.400", 8400), ("8,4 тыс", 8400), ("12 900", 12900), ("1.2M", 1200000)):
    run("result", "1", "--views", text, "--file", j)
    check(f"--views '{text}' = {want}", rows(j)[0]["views"] == want and isinstance(rows(j)[0]["views"], int))
run("result", "1", "--ctr", "6,2%", "--avp", "41.5", "--file", j)
check("--ctr '6,2%' и --avp '41.5' приняты", rows(j)[0]["ctr"] == 6.2 and rows(j)[0]["avp"] == 41.5)
run("result", "1", "--ctr", "0", "--avp", "100", "--file", j)
check("границы 0 и 100 приняты", rows(j)[0]["ctr"] == 0 and rows(j)[0]["avp"] == 100)
run("result", "1", "--views", "8400", "--ctr", "6,2", "--avp", "41", "--file", j)

e = rejected("result", "1", "--views", "8,4", "--file", j)
check("--views '8,4': дробные просмотры отклонены, флаг и значение названы", "--views" in e and "'8,4'" in e)
e = rejected("result", "1", "--views", "много", "--file", j)
check("--views 'много': не число", "--views" in e and "'много'" in e)
e = rejected("result", "1", "--views", "-5", "--file", j)
check("--views '-5': отрицательное отклонено", "--views" in e and "'-5'" in e)
e = rejected("result", "1", "--ctr", "64", "--file", j)
check("--ctr 64: выше 30 - просьба перепроверить", "--ctr" in e and "'64'" in e and "перепроверь" in e)
e = rejected("result", "1", "--ctr", "8400", "--file", j)
check("--ctr 8400: вне 0-100", "--ctr" in e and "'8400'" in e)
e = rejected("result", "1", "--avp", "140", "--file", j)
check("--avp 140: вне 0-100", "--avp" in e and "'140'" in e)
r = rows(j)[0]
check("отклонённые цифры ничего не изменили", (r["views"], r["ctr"], r["avp"]) == (8400, 6.2, 41))
check("result без цифр - ошибка", bool(rejected("result", "1", "--file", j)))
check("result для несуществующего номера - ошибка", "#99" in rejected("result", "99", "--views", "1", "--file", j))

# 2. вывод по-русски
out = run("result", "1", "--views", "8400", "--file", j)
check("подтверждение: '8 400 просмотров', а не '8,400'", "8 400 просмотров" in out and "8,400" not in out)
check("подтверждение: проценты с запятой", "CTR 6,2%" in out and "41%" in out)
out = run("list", "--file", j)
check("list: колонки и русская запись чисел", all(x in out for x in ("заголовок", "текст обложки", "просмотры", "CTR", "досмотр",
      "СЕРОЕ ПЯТНО", "8 400", "6,2%", "41%")) and "8,400" not in out and "6.2" not in out)
check("list: пустой журнал", "журнал пуст" in run("list", "--file", t("none.jsonl")))

# 3. отчёт: 1, 4 и 8 видео
out = run("report", "--file", j)
check("отчёт при 1 видео: таблица есть", all(x in out for x in ("#1", "Почему обложку пролистывают", "СЕРОЕ ПЯТНО", "8 400", "6,2%", "41%")))
check("отчёт при 1 видео: сказано, скольких не хватает", "только список" in out and "не хватает ещё 3" in out)
check("отчёт при 1 видео: сравнения нет", "медиана" not in out and "кратное" not in out)
run("add", "--title", "Без цифр", "--file", j)
out = run("report", "--file", j)
check("отчёт: видео без результатов тоже в таблице", "Без цифр" in out and "с результатами 1" in out)

f2 = lambda i: "Цифра" if i > 3 else "Ошибка"
j3, j4, j8 = journal("j3.jsonl", 3, f2), journal("j4.jsonl", 4, f2), journal("j8.jsonl", 8, f2)
out = run("report", "--file", j3)
check("отчёт при 3 видео: ещё список, не хватает 1", "только список" in out and "не хватает ещё 1" in out and "медиана" not in out)
out = run("report", "--file", j4)
check("отчёт при 4 видео: сравнение с пометкой 'предварительно'", "предварительно" in out and "медиана 2 500" in out and "кратное" in out)
check("отчёт при 4 видео: кратное с запятой", "1,60x" in out and "0,40x" in out and "1.60" not in out)
line = lambda out, word: next((l for l in out.splitlines() if word in l and " видео " in l and "#" not in l), "")
check("формула с 1 видео - 'мало данных', с 3 - нет", "мало данных" in line(out, "Цифра") and "мало данных" not in line(out, "Ошибка"))
out = run("report", "--file", j8)
check("отчёт при 8 видео: без 'предварительно'", "предварительно" not in out and "8 видео с результатами" in out and "медиана 4 500" in out)
check("отчёт при 8 видео: обе формулы без 'мало данных'", "мало данных" not in out)
check("отчёт: пустой журнал", "журнал пуст" in run("report", "--file", t("none.jsonl")))

# 4. --json у всех команд
jj = t("json.jsonl")
r = json.loads(run("add", "--title", "Три ошибки монтажа", "--hook", "Перестань резать по паузам", "--file", jj, "--json"))
check("add --json: записанная строка", r["id"] == 1 and r["title"] == "Три ошибки монтажа" and r["formula"] == "Ошибка")
r = json.loads(run("result", "1", "--views", "8,4 тыс", "--ctr", "5,1", "--file", jj, "--json"))
check("result --json: строка с цифрами", r["views"] == 8400 and r["ctr"] == 5.1)
r = json.loads(run("edit", "1", "--thumb", "НЕ РЕЖЬ", "--file", jj, "--json"))
check("edit --json: изменённая строка", r["thumb"] == "НЕ РЕЖЬ" and r["views"] == 8400)
r = json.loads(run("list", "--file", jj, "--json"))
check("list --json: список записей", isinstance(r, list) and r[0]["thumb"] == "НЕ РЕЖЬ" and r[0]["avp"] is None)
r = json.loads(run("report", "--file", jj, "--json"))
check("report --json при 1 видео: enough_data false, кратных нет", r["enough_data"] is False and r["need_more"] == 3
      and r["median"] is None and r["entries"][0]["multiple"] is None and r["formulas"] == [])
r = json.loads(run("report", "--file", j4, "--json"))
check("report --json при 4: enough_data, preliminary, медиана, кратные", r["enough_data"] is True and r["preliminary"] is True
      and r["median"] == 2500 and [x["multiple"] for x in r["entries"]] == [0.4, 0.8, 1.2, 1.6])
fm = {f["name"]: f for f in r["formulas"]}
check("report --json: сводка по формулам с few_data", r["formula_kind"] == "hook" and fm["Ошибка"]["n"] == 3
      and fm["Ошибка"]["few_data"] is False and fm["Цифра"]["few_data"] is True and fm["Цифра"]["multiple"] == 1.6)
r = json.loads(run("report", "--file", j8, "--json"))
check("report --json при 8: preliminary false", r["enough_data"] is True and r["preliminary"] is False)
check("report --json: пустой журнал - тоже json", json.loads(run("report", "--file", t("none.jsonl"), "--json"))["entries"] == [])

# 5. формулы: хук, заголовок, что показывать в отчёте
jf = t("formula.jsonl")
out = run("add", "--title", "Монтаж за вечер", "--hook", "Перестань резать по паузам", "--file", jf)
check("add: формула хука определена по словам и об этом сказано", rows(jf)[0]["formula"] == "Ошибка"
      and "формула определена по словам хука: Ошибка" in out)
out = run("add", "--title", "Как снять видео без камеры", "--file", jf)
r = rows(jf)[1]
check("add без хука: формулы хука нет, форма заголовка определена", r["formula"] is None and r["title_formula"] == "Вопрос из поиска"
      and "форма заголовка определена по словам заголовка: Вопрос из поиска" in out)
out = run("add", "--title", "Как снять видео без камеры", "--hook", "Перестань резать по паузам", "--formula", "Наоборот",
          "--title-formula", "Моя форма", "--file", jf)
r = rows(jf)[2]
check("add: названные автором формулы не переопределяются", r["formula"] == "Наоборот" and r["title_formula"] == "Моя форма"
      and "определена по словам" not in out)
out = run("add", "--title", "Монтаж", "--hook", "Монтаж бывает разный", "--file", jf)
check("add: хук без узнаваемой формы - формула пустая, сказано прямо", rows(jf)[3]["formula"] is None and "не определилась" in out)

jt = journal("titleonly.jsonl", 3)
run("add", "--title", "Как снять видео без камеры", "--views", "4000", "--file", jt)
out = run("report", "--file", jt)
check("отчёт без единого хука: сводка по форме заголовка, так и сказано", "по форме заголовка" in out and "Вопрос из поиска" in out
      and "по формулам хука" not in out)
check("report --json: formula_kind title", json.loads(run("report", "--file", jt, "--json"))["formula_kind"] == "title")
run("edit", "4", "--hook", "Перестань резать по паузам", "--file", jt)
out = run("report", "--file", jt)
check("отчёт, когда хук есть хотя бы у одного: сводка по формулам хука", "по формулам хука" in out and "по форме заголовка" not in out
      and "мало данных" in line(out, "Ошибка"))

# 6. edit
je = t("edit.jsonl")
run("add", "--title", "Старый заголовок", "--file", je)
out = run("edit", "1", "--hook", "Перестань резать по паузам", "--thumb", "НЕ РЕЖЬ", "--url", "https://youtu.be/x", "--note", "дослал позже", "--file", je)
r = rows(je)[0]
check("edit: хук, обложка, ссылка, заметка дописаны", (r["hook"], r["thumb"], r["url"], r["note"]) ==
      ("Перестань резать по паузам", "НЕ РЕЖЬ", "https://youtu.be/x", "дослал позже"))
check("edit: формула по новому хуку определена и названа", r["formula"] == "Ошибка" and "формула определена по словам хука: Ошибка" in out)
run("edit", "1", "--hook", "Все говорят, что нужна камера", "--file", je)
check("edit: автоматическая формула пересчитана под новый хук", rows(je)[0]["formula"] == "Наоборот")
run("edit", "1", "--formula", "Своя", "--title-formula", "Форма", "--file", je)
run("edit", "1", "--hook", "Перестань резать по паузам", "--title", "5 правил монтажа", "--file", je)
r = rows(je)[0]
check("edit: названная автором формула переживает смену хука и заголовка", r["formula"] == "Своя" and r["title_formula"] == "Форма"
      and r["title"] == "5 правил монтажа")
run("edit", "1", "--note", "", "--file", je)
check("edit: пустое значение стирает поле", rows(je)[0]["note"] is None)
check("edit: пустой заголовок отклонён", bool(rejected("edit", "1", "--title", " ", "--file", je)))
check("edit без полей - ошибка", bool(rejected("edit", "1", "--file", je)))
check("edit несуществующего номера - ошибка", "#7" in rejected("edit", "7", "--hook", "x", "--file", je))
check("edit: цифры - через result", "result" in rejected("edit", "1", "--views", "5", "--file", je))
check("неизвестная команда - одна строка", "frob" in rejected("frob", "--file", je))

# 7. даты
jd = t("date.jsonl")
today = datetime.date.today()
out = run("add", "--title", "Сегодняшнее", "--file", jd)
check("add без даты: сегодня, дата в подтверждении, подсказка про edit", rows(jd)[0]["date"] == today.isoformat()
      and today.strftime("%d.%m.%Y") in out and "edit 1 --date" in out)
run("add", "--title", "ISO", "--date", "2026-09-23", "--file", jd)
out = run("add", "--title", "Русская", "--date", "23.09.2026", "--file", jd)
check("даты 2026-09-23 и 23.09.2026 хранятся одинаково", rows(jd)[1]["date"] == rows(jd)[2]["date"] == "2026-09-23" and "23.09.2026" in out)
out = run("edit", "1", "--date", "01.09.2026", "--file", jd)
check("edit --date меняет дату", rows(jd)[0]["date"] == "2026-09-01" and "01.09.2026" in out)
for bad in ("вчера", "23/09/2026", "31.02.2026", "2026-13-01", "23.09.26"):
    e = rejected("add", "--title", "Плохая дата", "--date", bad, "--file", jd)
    check(f"дата '{bad}' отклонена", "--date" in e and f"'{bad}'" in e)
check("после отказов в журнале по-прежнему 3 записи", len(rows(jd)) == 3)

# 8. целость файла
check("после всех записей в папке нет временных файлов", sorted(os.listdir(tmp.name)) == sorted(x for x in os.listdir(tmp.name) if x.endswith(".jsonl")))
before = open(j8, encoding="utf-8").read()
code = ("import sys; sys.path.insert(0, sys.argv[1]); import journal\n"
        "try: journal.save(sys.argv[2], journal.load(sys.argv[2]) + [{'id': 9, 'title': object()}])\n"
        "except TypeError: print('сорвалось')\n")
p = subprocess.run([sys.executable, "-c", code, os.path.join(ROOT, "scripts"), j8], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", env=ENV)
check("сорванная запись: прежний журнал цел, мусора в папке нет", "сорвалось" in p.stdout
      and open(j8, encoding="utf-8").read() == before and len(rows(j8)) == 8 and not [x for x in os.listdir(tmp.name) if x.endswith(".tmp")])
run("add", "--title", "Девятое", "--file", j8)
check("запись в существующий журнал не теряет старые строки", [r["id"] for r in rows(j8)] == list(range(1, 10)))

with open(j8, "a", encoding="utf-8") as fh: fh.write('{"id": 10, "title": "обрыв\n')
for cmd in (("report",), ("list",), ("add", "--title", "Ещё одно"), ("result", "1", "--views", "5")):
    e = rejected(*(cmd + ("--file", j8)))
    check(f"испорченная строка: {cmd[0]} даёт понятную ошибку с номером строки", "строка 10 испорчена" in e)
check("испорченный журнал не перезаписан", len(open(j8, encoding="utf-8").read().splitlines()) == 10)

# 9. домашняя папка и справка
run("add", "--title", "В домашнюю папку")
check("без --file журнал пишется в YT_STUDIO_HOME", len(rows(os.path.join(t("home"), "journal.jsonl"))) == 1)
p = raw()
check("запуск без аргументов: справка и код 0", p.returncode == 0 and "journal.py add" in p.stdout and "edit" in p.stdout)

tmp.cleanup()
print("\n" + ("ВСЁ ПРОШЛО" if not fails else f"ПРОВАЛОВ: {len(fails)}\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
