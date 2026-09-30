#!/usr/bin/env python3
"""Проверка hook.py: только механические ошибки, заметки "?" без штрафа, формы запрещённых слов,
шаблоны формул, RU и EN. Запуск: python3 tests/test_hook.py"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "scripts", "hook.py")
fails = []
tmp = tempfile.TemporaryDirectory()
t = lambda name: os.path.join(tmp.name, name)
# пустая домашняя папка: настоящий voice.md автора в проверках не участвует
ENV = dict(os.environ, YT_STUDIO_HOME=t("home"), PYTHONIOENCODING="utf-8")
os.environ["YT_STUDIO_HOME"] = t("home")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from ytlib import find_banned, load_formulas, classify, NUM_WORDS

def proc(*args):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=ENV)

def run(*args, code=0):
    p = proc(*args)
    if p.returncode != code: fails.append(f"hook.py {args}: код {p.returncode}, ждали {code}\n{p.stderr}")
    return p.stdout

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

def one(hook, *extra):
    return json.loads(run("--hook", hook, *(extra + ("--json",))))[0]

def write(name, text):
    with open(t(name), "w", encoding="utf-8") as f: f.write(text)
    return t(name)

kinds = lambda r: {i["kind"] for i in r["issues"]}
notes = lambda r: " | ".join(r["notes"])
good = lambda r: " | ".join(r["good"])
forms = load_formulas()
STUFFED = "Почему ты зря тратишь 100 часов, но почти никто не знает, что и как ты теряешь?"
WEAK = "Всем привет, сегодня я расскажу про невероятный лайфхак"

# 1. калибровка: примеры формул чистые, набивка ключевыми словами ничем не награждается
rows = json.loads(run(write("examples.txt", "\n".join(f["example"] for f in forms) + "\n"), "--json"))
dirty = [(r["hook"], sorted(kinds(r))) for r in rows if r["issues"]]
check(f"все {len(forms)} примеров из hooks.json проходят без единой ошибки", len(rows) == len(forms) and not dirty)
for x in dirty: print("      ", x)
s = one(STUFFED)
check("набивка ключевыми словами не получает больше, чем примеры", s["score"] <= min(r["score"] for r in rows))
check("json: поля по договору, без свойств и вердикта",
      {"hook", "score", "issues", "notes", "good", "formula", "seconds", "words"} <= set(s)
      and not {"properties", "verdict", "band", "flags", "weakest"} & set(s))
r = one(WEAK, "--voice", os.path.join(ROOT, "tests", "data", "voice.md"))
check("штамп, вода и слово не из голоса - три ошибки, балл ниже", {"штамп", "вода", "голос"} <= kinds(r) and r["score"] < 60)
check("без voice.md тот же хук всё равно с ошибками", {"штамп", "вода"} <= kinds(one(WEAK)))
out = run("--hook", STUFFED) + run("--hook", WEAK)
check("в выводе нет полос и слова 'лучший'", not any(w in out for w in ("СИЛЬНЫЙ", "РАБОЧИЙ", "СЛАБЫЙ", "ВЕРДИКТ", "лучший")))

# 2. каждый вид ошибки, RU и EN
def has(kind, hook, *extra): return kind in kinds(one(hook, *extra))
check("штамп RU: 'в этом видео'", has("штамп", "В этом видео три причины, по которым новички бросают бег"))
check("штамп RU: приветствие в начале", has("штамп", "Привет! Три причины, по которым новички бросают бег"))
check("штамп EN: 'hey guys'", has("штамп", "Hey guys, three reasons beginners quit running in week two"))
check("представление RU: 'меня зовут'", has("представление", "Меня зовут Вася, и я бегаю шесть лет без травм"))
check("представление RU: 'я Имя'", has("представление", "Я Вася, тренер по бегу, и вот три ошибки новичков"))
check("представление EN: 'my name is'", has("представление", "My name is John and these are three running mistakes"))
check("представление EN: \"I'm Name\"", has("представление", "I'm John, a running coach, and here are three mistakes"))
check("'меня зовут' не штрафуется дважды как штамп", "штамп" not in kinds(one("Меня зовут Вася, и я бегаю шесть лет без травм")))
check("рассказ от первого лица - не представление", not has("представление", "Я два года монтировал чужие каналы и вот что понял"))
check("подписка RU", has("подписка", "Подпишись на канал, и я расскажу три причины бросить бег"))
check("подписка EN", has("подписка", "Subscribe first, then I will show you three running mistakes"))
check("'подписчиков' - не просьба подписаться", not has("подписка", "Если у тебя меньше тысячи подписчиков, это для тебя"))
check("вода RU", has("вода", "Это невероятный способ пробежать десять километров без подготовки"))
check("вода EN", has("вода", "This is the ultimate way to run ten kilometers"))
long_ru, long_en = " ".join(["слово"] * 39), " ".join(["word"] * 43)
r = one(long_ru)
check("длинно RU: 39 слов - ошибка, секунды названы", "длинно" in kinds(r) and r["words"] == 39 and r["seconds"] == 18
      and "около 18 с" in r["issues"][0]["msg"])
check("длинно RU: 38 слов проходят", "длинно" not in kinds(one(" ".join(["слово"] * 38))))
r = one(" ".join(["слово"] * 35))
check("35 русских слов: не ошибка (старый порог был 24), а заметка про границу 15 с", not r["issues"] and "на границе" in notes(r))
r = one(long_en)
check("длинно EN: 43 слова - ошибка, темп английский", "длинно" in kinds(r) and r["seconds"] == 17 and r["lang"] == "en")
check("длинно EN: 42 слова проходят", "длинно" not in kinds(one(" ".join(["word"] * 42))))
check("язык определяется по каждому хуку", one("Почему бросают бег на второй неделе")["lang"] == "ru")
check("коротко RU: 4 слова", has("коротко", "Почему бросают бег новички"))
check("коротко EN: 3 слова", has("коротко", "Why beginners quit"))
check("5 слов - уже не коротко", not has("коротко", "Почему новички бросают бег рано"))
check("сам-ответ RU", has("сам-ответ", "Почему новички бросают бег? Потому что начинают слишком быстро."))
check("сам-ответ EN", has("сам-ответ", "Why do beginners quit running? Because they start too fast."))
check("'потому что' без вопроса до него - не ошибка", not has("сам-ответ", "Новички бросают бег, потому что начинают слишком быстро"))
check("вопрос без ответа - не ошибка", not has("сам-ответ", "Почему новички бросают бег на второй неделе?"))
check("паразиты RU: три и больше", has("паразиты", "Ну вообще это просто три причины, по которым бросают бег"))
check("паразиты EN", has("паразиты", "So basically this is literally the reason you actually quit running"))
check("два слова-паразита - ещё не ошибка", not has("паразиты", "Это просто три причины, по которым вообще бросают бег"))
v = write("voice.md", "# Голос\n\n## Слова, которые я не использую\n- мотивация, дисциплина\n- «давай без воды»\n")
r = one("Дело не в мотивации и не в дисциплине, а в трёх привычках", "--voice", v)
check("голос: слово в другом падеже поймано и названо как в списке",
      "голос" in kinds(r) and "мотивация" in str(r["issues"]) and "дисциплина" in str(r["issues"]))
check("голос: чистый хук получает 'ok'", "не из твоего голоса нет" in good(one("Три привычки вместо силы воли", "--voice", v)))
r = one("Hey guys, my name is John, subscribe for the ultimate trick, because why not? Because.")
check("балл = 100 минус веса, не ниже нуля", r["score"] == max(0, 100 - 25 - 20 - 20 - 15 - 15) and len(r["issues"]) == 5)

# 3. заметки "?" - наблюдения без штрафа
r = one("Почему у видео много показов и почти нет кликов?")
check("нет числа/имени - заметка, не ошибка", "нет числа/имени - проверь, не абстрактно ли" in notes(r) and r["score"] == 100)
check("нет обращения - нейтральная заметка, не ошибка", "обращения к зрителю нет" in notes(r) and "нормально" in notes(r))
check("формула названа вместе с понятной фразой", 'Вопрос из поиска' in notes(r) and "задаём вопрос" in notes(r) and r["formula"] == "Вопрос из поиска")
r = one("Бегать по утрам легче, когда кроссовки стоят у двери")
check("формула не узнана: заметка без 'это пересказ'", "ни с одной формулой" in notes(r) and "пересказ" not in notes(r)
      and r["formula"] == "не определена" and not r["issues"])
check("конкретика: цифра", "число" in good(one("Я пробежал 42 километра и вот что понял про темп")))
check("конкретика: число словом в косвенном падеже", "тридцати" in good(one("Видео не досматривают из-за первых тридцати секунд")))
check("конкретика: порядковое ('на второй неделе')", "второй" in good(one("Бросают бег обычно на второй неделе тренировок")))
check("конкретика EN: one/two - числа", "two" in good(one("Most beginners quit running after two weeks")) and "one" in NUM_WORDS)
check("'одно и то же' - не число", "одно" not in NUM_WORDS and "нет числа/имени" in notes(one("Ты делаешь одно и то же каждое утро")))
r = one("Это видео про бег. Новички часто бросают. Почему так выходит?")
check("заглавная в начале предложения - не имя", "нет числа/имени" in notes(r))
check("имя в середине фразы - конкретика", "Дудя" in good(one("Так начинал канал Дудя, и это видно по первым видео")))
check("площадка - не имя", "нет числа/имени" in notes(one("Как набрать просмотры на YouTube без рекламы и бюджета")))
def addr(h): return "зритель назван" in good(one(h))
check("обращение: местоимение", addr("Твои видео не досматривают из-за первых секунд"))
check("обращение: повелительное ('проверь', 'слушай', 'скажи')", all(addr(h) for h in (
      "Проверь шнуровку перед пробежкой прямо сейчас", "Слушай, бег на пустой желудок работает иначе", "Скажи честно, сколько пробежек было в мае")))
check("обращение: глагол второго лица ('бежишь')", addr("Если бежишь через боль, колено скажет спасибо позже"))
check("обращение: вопрос в прошедшем времени ('Бросил бегать?')", addr("Бросил бегать? На второй неделе так делают почти все."))
check("'в интернете' - не глагол второго лица", not addr("В интернете много советов про бег по утрам"))
check("обращение EN: you и повелительное в начале", addr("This is why your knees hurt after running") and addr("Stop stretching before every single run"))
check("обращение EN: рассказ о себе - без обращения", not addr("I ran every day for thirty days"))
out = run("--hook", "Почему у видео много показов и почти нет кликов?")
check("текстовый вывод: заметки под '?', пройденное под 'ok', без балла у чистого хука",
      any(l.strip().startswith("?") for l in out.splitlines()) and any(l.strip().startswith("ok") for l in out.splitlines())
      and "/100" not in out and "механических ошибок нет" in out)
check("текстовый вывод: у хука с ошибками - 'x' и балл", "    x  штамп" in run("--hook", WEAK) and "/100" in run("--hook", WEAK))

# 4. несколько хуков: порядок и итоговая строка
clean = ["Почему новички бросают бег на второй неделе?", "Три привычки, которые держат бегуна дольше месяца", STUFFED]
f = write("hooks.txt", "\n".join([clean[0], WEAK, "", "2. " + clean[1], '- "' + clean[2] + '"']) + "\n")
rows = json.loads(run(f, "--json"))
check("ничья: порядок как в файле, хук с ошибками - в конце", [r["hook"] for r in rows] == clean + [WEAK])
check("файл: номера, маркеры списка и кавычки вокруг хука убраны", rows[1]["hook"] == clean[1] and rows[2]["hook"] == clean[2])
out = run(f)
check("итог: 'Хуков без механических ошибок: 3' и суждение о смысле", "Хуков без механических ошибок: 3. Проверка между ними не выбирает: "
      "выбор - это суждение о смысле." in out and "лучший" not in out)
check("один хук: итоговой строки нет", "Хуков без механических ошибок" not in run("--hook", clean[0]))

# 5. файлы и параметры
p = proc(t("нет-такого.txt"))
check("нет файла: сказано 'нет файла', а не 'не задан текст'", p.returncode == 1 and "нет файла:" in p.stderr and "не задан" not in p.stderr)
p = proc(write("empty.txt", "\n  \n"))
check("файл без хуков: понятная ошибка", p.returncode == 1 and "Traceback" not in p.stderr and p.stderr.strip())
p = proc("--hook", clean[0], "--voice", t("нет-voice.md"), "--json")
check("--voice на несуществующий файл: одна строка в stderr, результат есть",
      p.returncode == 0 and len(p.stderr.strip().splitlines()) == 1 and "нет файла" in p.stderr and json.loads(p.stdout))
p = proc("--hook", clean[0], "--voice", v)
check("--voice на существующий файл: stderr пуст", p.returncode == 0 and not p.stderr.strip())
check("справка без аргументов", proc().returncode == 0 and "hook.py" in proc().stdout)

# 6. формы запрещённых слов (ytlib.find_banned)
B = ["мотивация", "дисциплина", "лайфхак", "погнали", "давай без воды", "тема", "ошибка", "hack", "невероятный", "жесть"]
caught = {"про мотивации": "мотивация", "мотивацию ищут": "мотивация", "с мотивацией": "мотивация", "Дисциплину": "дисциплина",
          "нет дисциплин": "дисциплина", "три лайфхака": "лайфхак", "ПОГНАЛИ!": "погнали", "Ну давай БЕЗ воды": "давай без воды",
          "в этой теме": "тема", "пять ошибок": "ошибка", "одной ошибкой": "ошибка", "life hacks": "hack", "stop hacking": "hack",
          "невероятно просто": "невероятный", "невероятных историй": "невероятный", "вот жести-то": "жесть"}
bad = [(k, find_banned(k, B)) for k, w in caught.items() if find_banned(k, B) != [w]]
check(f"формы слова ловятся и возвращаются словарной записью ({len(caught)} случаев)", not bad)
for x in bad: print("      ", x)
free = ["мотив песни", "мотивировать команду", "мотивационный ролик", "дисциплинированный", "тем более", "ошибочный ход",
        "hacker", "shack", "жест доброй воли", "водитель", "давай без"]
bad = [(k, find_banned(k, B)) for k in free if find_banned(k, B)]
check(f"однокоренные и похожие слова не ловятся ({len(free)} случаев)", not bad)
for x in bad: print("      ", x)
check("запись возвращается один раз", find_banned("мотивация, мотивации, мотивацию", B + ["мотивация"]) == ["мотивация"])

# 7. формулы: естественные формулировки
cases = [("Проблема не в лени", ("Ошибка",)), ("Ты ошибся с выбором кроссовок", ("Ошибка",)),
         ("Я бегаю шесть лет и ни разу не травмировался", ("Изнутри",)), ("I've been running for six years", ("Изнутри",)),
         ("Я две недели бегал каждый день и записывал пульс", ("Я попробовал",)),
         ("Everyone stretches first. That's wrong.", ("Наоборот",)), ("That is wrong", ("Наоборот",)),
         ("Как я пробежал марафон без подготовки", ("Я попробовал", "Невозможное заявление")),
         ("How I ran a marathon with no training", ("Я попробовал", "Невозможное заявление")),
         ("5 ошибок новичка", ("Ошибка", "Список")), ("Как пробежать марафон без подготовки?", ("Вопрос из поиска",)),
         ("How to run a marathon", ("Вопрос из поиска",))]
bad = [(h, classify(h, forms)[0]) for h, want in cases if classify(h, forms)[0] not in want]
check(f"формулы узнают естественные формулировки ({len(cases)} случаев)", not bad)
for x in bad: print("      ", x)
wrong = [f["name"] for f in forms if classify(f["example"], forms)[0] != f["name"]]
check("каждая формула по-прежнему узнаёт свой пример", not wrong)
check("у каждой формулы есть user_phrase - строка простыми словами",
      all(isinstance(f.get("user_phrase"), str) and 15 < len(f["user_phrase"]) < 90 for f in forms))

tmp.cleanup()
print("\n" + ("ВСЁ ПРОШЛО" if not fails else f"ПРОВАЛОВ: {len(fails)}\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
