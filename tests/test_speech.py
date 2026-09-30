#!/usr/bin/env python3
"""Проверка speech.py: счёт произносимых слов, блоки и таймкоды, --target, --wpm, слова не из голоса,
блоки без картинки, RU и EN. Запуск: python3 tests/test_speech.py"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "scripts", "speech.py")
fails = []
tmp = tempfile.TemporaryDirectory()
t = lambda name: os.path.join(tmp.name, name)
# пустая домашняя папка: настоящий voice.md автора в проверках не участвует
ENV = dict(os.environ, YT_STUDIO_HOME=t("home"), PYTHONIOENCODING="utf-8")

def proc(*args):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=ENV)

def run(*args, code=0):
    p = proc(*args)
    if p.returncode != code: fails.append(f"speech.py {args}: код {p.returncode}, ждали {code}\n{p.stderr}")
    return p.stdout

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

def write(name, text):
    with open(t(name), "w", encoding="utf-8") as f: f.write(text)
    return t(name)

def js(*args): return json.loads(run(*(args + ("--json",))))
words = lambda n, w="слово": " ".join([w] * n)

# 1. счёт: сценарий с известным числом слов (13 + 11 + 260 + 4 = 288)
script = write("script.md", f"""# Сценарий: почему бросают бег

## Хук (0:00–0:15)
[НА ЭКРАНЕ: трекер с пробежками за май]
Бросил бегать? На второй неделе так делают почти все. [пауза] Дело не в лени.

**Поворот (0:15-0:20)**
Сейчас покажу три причины - и начнём с той, что про кроссовки.

---

## Блок 1. Темп
> {words(130)}
- {words(60)}
2. {words(62)}
*Про мотивацию* говорить не буду, (1:10-1:40) только про **дисциплину**.

## Пустой блок
[НА ЭКРАНЕ: график]

## Финал
[ON SCREEN: next video]
Следующее видео - про пульс.
""")
r = js(script)
B = {b["name"]: b for b in r["blocks"]}
check("слова считаются только произносимые: 288", r["words"] == 288)
check("блоки по заголовкам '#' и '**жирным**', таймкоды из названий убраны, пустые блоки выпали",
      [b["name"] for b in r["blocks"]] == ["Хук", "Поворот", "Блок 1. Темп", "Финал"])
check("хук: пометка в скобках, строка [НА ЭКРАНЕ] и таймкод в заголовке не посчитаны", B["Хук"]["words"] == 13)
check("жирный заголовок не посчитан как речь", B["Поворот"]["words"] == 11)
check("маркеры цитат и списков, таймкод в скобках и звёздочки не посчитаны", B["Блок 1. Темп"]["words"] == 260)
check("строка [ON SCREEN: ...] не посчитана", B["Финал"]["words"] == 4)
check("русский текст: темп 120-140 по умолчанию", r["lang"] == "ru" and r["wpm"] == [120, 140])
check("вилка длительности: 288 слов = 2:03-2:24", r["seconds"] == [123, 144])
check("блок: вилка секунд из числа слов", B["Блок 1. Темп"]["seconds"] == [111, 130])
check("таймкоды блоков идут подряд от нуля при среднем темпе",
      r["blocks"][0]["start"] == 0 and all(a["end"] == b["start"] for a, b in zip(r["blocks"], r["blocks"][1:]))
      and r["blocks"][-1]["end"] == 133 and B["Блок 1. Темп"]["start"] == 11)
out = run(script)
check("текстовый вывод: строка блока со словами, вилкой и таймкодом",
      any(l.split()[:3] == ["Блок", "1.", "Темп"] and l.split()[3:] == ["260", "1:51-2:10", "0:11-2:11"] for l in out.splitlines())
      and any(l.split() == ["всего", "288", "2:03-2:24"] for l in out.splitlines()))
r = js(write("plain.md", "Просто текст без заголовков.\nВторая строка текста.\n"))
check("текст без заголовков - один блок", len(r["blocks"]) == 1 and r["words"] == 7)

# 2. --wpm
r = js(script, "--wpm", "144")
check("--wpm числом: одна длительность вместо вилки", r["wpm"] == [144, 144] and r["seconds"] == [120, 120])
check("--wpm вилкой", js(script, "--wpm", "100-160")["seconds"] == [108, 173])
for bad in ("быстро", "10", "120-"):
    p = proc(script, "--wpm", bad)
    check(f"--wpm '{bad}': понятная ошибка", p.returncode == 1 and "--wpm" in p.stderr and "Traceback" not in p.stderr)

# 3. --target
r = js(script, "--target", "5:00")
check("--target: не хватает слов, разница вилкой", r["target"]["verdict"] == "short" and r["target"]["need_words"] == [600, 700]
      and r["target"]["delta_words"] == [310, 410])
check("--target: текст 'до 5:00 не хватает 310-410 слов'", "до 5:00 не хватает 310-410 слов" in run(script, "--target", "5:00"))
r = js(script, "--target", "1:30")
check("--target: лишние слова", r["target"]["verdict"] == "long" and "для 1:30 лишние 80-110 слов" in run(script, "--target", "1:30"))
check("--target секундами, длина попадает", js(script, "--target", "135")["target"]["verdict"] == "fits"
      and "длина попадает в 2:15" in run(script, "--target", "135"))
check("без --target поля нет", js(script)["target"] is None)
p = proc(script, "--target", "пять минут")
check("--target не временем: понятная ошибка", p.returncode == 1 and "--target" in p.stderr and "Traceback" not in p.stderr)

# 4. слова не из голоса
v = write("voice.md", "# Голос\n\n## Слова, которые я не использую\n- мотивация, дисциплина, кроссовки-убийцы\n- «график»\n")
r = js(script, "--voice", v)
check("запрещённые слова в теле найдены в других падежах, с блоком и строкой",
      [(x["word"], x["block"]) for x in r["banned"]] == [("мотивация", "Блок 1. Темп"), ("дисциплина", "Блок 1. Темп")]
      and "Про мотивацию говорить не буду" in r["banned"][0]["line"])
check("слово внутри пометки [НА ЭКРАНЕ] - не речь, не ловится", "график" not in [x["word"] for x in r["banned"]])
out = run(script, "--voice", v)
check("текстовый вывод: слово, блок и строка", 'x  слово не из голоса автора: мотивация - блок "Блок 1. Темп": Про мотивацию' in out)
check("без запрещённых слов в тексте: 'ok'", "ok слов не из голоса автора нет" in run(write("clean.md", "## Блок\nТри привычки бегуна.\n"), "--voice", v))
os.makedirs(t("home"), exist_ok=True)
write("home/voice.md", "## Слова, которые я не использую\n- пульс\n")
check("voice.md из домашней папки подхватывается без --voice", [x["word"] for x in js(script)["banned"]] == ["пульс"])
os.remove(t("home/voice.md"))
check("нет voice.md: проверки голоса нет, об этом сказано в json", js(script)["banned"] == [] and js(script)["voice_checked"] is False)
p = proc(script, "--voice", t("нет-voice.md"))
check("--voice на несуществующий файл: одна строка в stderr, отчёт есть",
      p.returncode == 0 and len(p.stderr.strip().splitlines()) == 1 and "нет файла" in p.stderr and "всего" in p.stdout)

# 5. блоки без картинки
r = js(script)
check("блок дольше 90 с без [НА ЭКРАНЕ] помечен, короткие и с пометкой - нет", r["no_visual"] == ["Блок 1. Темп"]
      and B["Хук"]["visual"] and not B["Блок 1. Темп"]["visual"])
check("текстовый вывод: замечание про блок без картинки", 'x  блок "Блок 1. Темп": около 2:00 речи без пометки' in run(script))
seen = write("seen.md", f"## Блок\n{words(130)}\n[НА ЭКРАНЕ: запись экрана]\n{words(130)}\n")
check("тот же объём с пометкой [НА ЭКРАНЕ] - без замечания", js(seen)["no_visual"] == [] and "ok блоков длиннее 90 с" in run(seen))
check("ровно 90 с без пометки - ещё не замечание", js(write("edge.md", "## Блок\n" + words(195) + "\n"))["no_visual"] == [])

# 6. английский
en = write("en.md", f"# Script\n\n## Hook (0:00-0:10)\n[ON SCREEN: running log]\nQuit running? Most people do in week two.\n\n"
                    f"## Body\n{words(300, 'word')}\n")
r = js(en)
check("EN: язык и темп 140-160", r["lang"] == "en" and r["wpm"] == [140, 160])
check("EN: слова и длительность", r["words"] == 308 and r["blocks"][0]["words"] == 8 and r["seconds"] == [116, 132])
check("EN: блок без [ON SCREEN] дольше 90 с помечен", r["no_visual"] == ["Body"])
check("EN: заголовок отчёта называет язык", "английский текст, темп 140-160" in run(en))
check("апостроф и дефис внутри слова - одно слово", js(write("apos.md", "Don't stop: как-то из-за well-known\n"))["words"] == 5)

# 7. ошибки входа
p = proc(t("нет-такого.md"))
check("нет файла: одна понятная строка", p.returncode == 1 and p.stderr.strip() == "нет файла: " + t("нет-такого.md"))
p = proc(write("empty.md", "  \n\n"))
check("пустой файл: понятная ошибка", p.returncode == 1 and "файл пустой" in p.stderr and "Traceback" not in p.stderr)
p = proc(write("notes.md", "# Заголовок\n[НА ЭКРАНЕ: лицо]\n"))
check("только заголовки и пометки: понятная ошибка", p.returncode == 1 and "нет текста" in p.stderr)
p = proc("--target", "5:00")
check("не задан файл: понятная ошибка", p.returncode == 1 and "Traceback" not in p.stderr and p.stderr.strip())
p = proc()
check("справка без аргументов", p.returncode == 0 and "speech.py" in p.stdout and not p.stderr.strip())
cp = write("cp1251.md", "")
with open(cp, "wb") as f: f.write("## Блок\r\nТри привычки бегуна.\r\n".encode("cp1251"))
check("файл в Windows-1251 с CRLF читается", js(cp)["words"] == 3)

tmp.cleanup()
print("\n" + ("ВСЁ ПРОШЛО" if not fails else f"ПРОВАЛОВ: {len(fails)}\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
