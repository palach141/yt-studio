#!/usr/bin/env python3
"""Проверка chapters.py: авто-число глав, --cuts, дубли, --check. Запуск: python3 tests/test_chapters.py"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL, D = os.path.join(ROOT, "scripts", "chapters.py"), os.path.join(ROOT, "tests", "data")
fails = []

def run(*args):
    p = subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

def srt(path, rows):
    ts = lambda t: "%02d:%02d:%02d,%03d" % (t // 3600, t % 3600 // 60, t % 60, round(t % 1 * 1000))
    open(path, "w", encoding="utf-8").write("".join(f"{n}\n{ts(a)} --> {ts(b)}\n{text}\n\n" for n, (a, b, text) in enumerate(rows, 1)))

d = lambda f: os.path.join(D, f)
talk = d("talk.srt")
starts = lambda r: [c["start"] for c in r["chapters"]]

# ---- число глав по длине видео
code, out, _ = run(talk, "--json")
r = json.loads(out)
check("авто: на 82 секундах выбрано 4 главы", code == 0 and r["auto_target"] and r["target"] == 4)
check("авто: границы стоят на началах четырёх тем", starts(r) == [0, 24.0, 47.7, 66.0] and r["valid"] and r["timeline"] == "source")
check("авто: вывод одинаков от запуска к запуску", out == run(talk, "--json")[1])
_, out, _ = run(talk)
check("авто: сказано, сколько выбрано и что это меняется через --target", "не больше 4" in out and "--target" in out and "ВЫРЕЗАНН" not in out)
r7 = json.loads(run(talk, "--target", "7", "--json")[1])
check("--target задан явно: авто не вмешивается", r7["target"] == 7 and not r7["auto_target"] and len(r7["chapters"]) > 4)
check("--target 2: понятная ошибка", run(talk, "--target", "2")[0] == 1)

# ---- дубль после фальстарта главу не открывает
check("дубль: \"Лицо на обложке держит...\" после фальстарта не граница", 35.8 not in starts(r7) and 31.6 not in starts(r7))

with tempfile.TemporaryDirectory() as tmp:
    t = lambda name: os.path.join(tmp, name)
    def cuts(name, keep, **extra):
        json.dump(dict({"keep": keep, "out": round(sum(b - a for a, b in keep), 3)}, **extra), open(t(name), "w"))
        return t(name)

    # Две темы; вторая открывается фальстартом и его пересказом после паузы - самое "границеподобное" место
    rows = [(i * 3.0, i * 3.0 + 2.8, f"Заголовок видео решает клики пример {i}") for i in range(6)]
    rows += [(21.0, 23.8, "Теперь обложка это контраст"), (24.0, 25.0, "Главный цвет обложки должен"), (25.2, 25.6, "э-э"),
             (28.5, 31.3, "Главный цвет обложки спорит с фоном")]
    rows += [(31.5 + i * 3.0, 34.3 + i * 3.0, f"Обложка держит контраст цвета фона {i}") for i in range(6)]
    srt(t("retake.srt"), rows)
    r = json.loads(run(t("retake.srt"), "--target", "3", "--json")[1])
    check("дубль: на своём примере граница встала на начало темы, а не на пересказ", 21.0 in starts(r) and 28.5 not in starts(r))

    # ---- --cuts: вырезаны 3-6, 21.5-24 и 30-36 (дубль целиком), хвост после 80
    keep = [[0, 3], [6, 21.5], [24, 30], [36, 80]]
    code, out, _ = run(talk, "--cuts", cuts("cut.json", keep), "--json")
    r = json.loads(out)
    # 24.0 -> 18.5; 47.7 -> 3+15.5+6+11.7 = 36.2; 66.0 -> 54.5
    check("--cuts: метки пересчитаны на вырезанную версию", code == 0 and starts(r) == [0, 18.5, 36.2, 54.5] and r["timeline"] == "cut")
    check("--cuts: проверка по длине после реза, блок валиден", r["valid"] and r["duration"] == 68.5 and r["chapters"][-1]["seconds"] == 14.0)
    check("--cuts: первые фразы глав те же, вырезанное в названия не идёт",
          r["chapters"][1]["first_line"].startswith("Теперь обложка") and "должна" not in r["chapters"][1]["draft_title"])
    _, out, _ = run(talk, "--cuts", t("cut.json"))
    check("--cuts: в выводе прямо сказано, что время для вырезанной версии", "ДЛЯ ВЫРЕЗАННОЙ ВЕРСИИ" in out and "0:18" in out and "--duration 1:08" in out)

    # граница внутри вырезанного куска встаёт на начало следующего оставленного
    r = json.loads(run(talk, "--cuts", cuts("inside.json", [[0, 21.5], [27.1, 81.8]]), "--json")[1])
    check("--cuts: граница из вырезанного куска - на начало следующего оставленного",
          starts(r)[1] == 21.5 and r["chapters"][1]["first_line"].startswith("Обложка не должна"))

    # тема "обложка" вырезана почти целиком: 24.0 -> 21.5, 47.7 -> 25.2, меньше 10 секунд
    code, out, _ = run(talk, "--cuts", cuts("collapse.json", [[0, 21.5], [44, 81.8]]), "--json")
    r = json.loads(out)
    check("--cuts: слипшиеся границы - поздняя убрана, блок остался валидным",
          code == 0 and starts(r) == [0, 21.5, 43.5] and r["valid"] and [x["source"] for x in r["dropped"]] == ["0:47"])
    _, out, _ = run(talk, "--cuts", t("collapse.json"))
    check("--cuts: об убранной границе сказано", "граница 0:47 исходника убрана" in out and "глав: 3" in out)
    r = json.loads(run(talk, "--cuts", cuts("tail.json", [[0, 70]]), "--json")[1])
    check("--cuts: последняя глава короче 10 секунд после реза - метка убрана", starts(r) == [0, 24.0, 47.7] and r["valid"] and len(r["dropped"]) == 1)
    json.dump({"keep": keep}, open(t("noout.json"), "w"))
    r = json.loads(run(talk, "--cuts", t("noout.json"), "--json")[1])
    check("--cuts: без ключа out длина считается по keep", r["duration"] == 68.5)

    # ---- кривой --cuts: одна строка, без трейсбека
    open(t("bad1.json"), "w").write("{не json")
    open(t("bad2.json"), "w").write('{"cuts": []}')
    open(t("bad3.json"), "w").write('{"keep": [[5, 1]], "out": 4}')
    open(t("bad4.json"), "w").write('{"keep": "строка", "out": 4}')
    open(t("bad5.json"), "w").write('[1, 2]')
    open(t("bad6.json"), "w").write('{"keep": [], "out": 0}')
    bad = []
    for f in ("bad1.json", "bad2.json", "bad3.json", "bad4.json", "bad5.json", "bad6.json", "нет-такого.json"):
        code, out, err = run(talk, "--cuts", t(f))
        if code != 1 or out or len(err.strip().splitlines()) != 1 or "Traceback" in err: bad.append((f, code, err[:200]))
    check("--cuts: кривой или отсутствующий файл - ошибка в одну строку", not bad)
    for b in bad: print("      ", b)

    # ---- --check
    ok, badf = d("chapters_ok.txt"), d("chapters_bad.txt")
    code, out, _ = run("--check", ok, "--duration", "1:21")
    check("--check с --duration: ГОДИТСЯ, без оговорок, код 0", code == 0 and "ГОДИТСЯ" in out and "!" not in out and "  x  " not in out)
    code, out, _ = run("--check", ok)
    check("--check без --duration: заголовок честный, заметка через '!', код 0",
          code == 0 and "ГОДИТСЯ" not in out and "ПРАВИЛА СОБЛЮДЕНЫ, но последняя глава не проверена: дай --duration" in out
          and "    !  " in out and "  x  " not in out)
    r = json.loads(run("--check", ok, "--json")[1])
    check("--check без --duration, json: правила соблюдены, но проверка неполная", r["valid"] and not r["complete"] and not r["errors"] and r["notes"])
    code, out, _ = run("--check", badf)
    check("--check: нарушение правил - код 2 и НЕ СТАНЕТ ГЛАВАМИ", code == 2 and "НЕ СТАНЕТ ГЛАВАМИ" in out and "  x  " in out)
    check("--check: счёт без \"2 меток\"", "меток: 2 - нужно минимум 3" in out and "2 меток" not in out and "меток 2" not in out)
    code, out, _ = run("--check", ok, "--duration", "0:45")
    check("--check: последняя глава короче 10 секунд - код 2", code == 2 and "последняя глава короче 10 секунд" in out)
    open(t("cut.txt"), "w", encoding="utf-8").write("0:00 Кому это видео\n0:18 Три слова на обложке\n0:36 Что показывает удержание\n0:54 Монтаж без пауз\n")
    check("--check: блок для вырезанной версии проходит с её длиной", run("--check", t("cut.txt"), "--duration", "1:08")[0] == 0)

print("\n" + ("ВСЁ ПРОШЛО" if not fails else f"ПРОВАЛОВ: {len(fails)}\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
