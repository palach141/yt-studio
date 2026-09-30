#!/usr/bin/env python3
"""journal.py - журнал канала: что вышло, с какой упаковкой, и что из этого получилось.

    python3 journal.py add --title "..." [--thumb "..."] [--hook "..."] [--formula "Ошибка"]
                           [--title-formula "Список"] [--url ...] [--date 2026-09-30 | 30.09.2026]
    python3 journal.py result 3 --views 12400 --ctr 5,1 --avp 42 [--note "..."]
    python3 journal.py edit 3 --hook "..." --date 23.09.2026
    python3 journal.py list
    python3 journal.py report

--formula - формула ХУКА (первой произнесённой фразы), --title-formula - форма заголовка. Если их не
указать, они определяются по словам хука и заголовка. edit меняет любое поле (title, thumb, hook,
formula, title-formula, url, date, note); пустое значение стирает поле. Цифры понимаются так, как
их пишут люди: 8400, "8 400", 8.400, "8,4 тыс", "6,2%"; add тоже принимает --views/--ctr/--avp -
для старых видео, у которых цифры уже есть. У всех команд есть --json.

Зачем: линтеры меряют слова, а не твой канал. Журнал копит твои собственные данные - какая формула
хука и какая упаковка дали какой результат именно у тебя, - и report показывает это как кратное
твоей же медианы. Цифры вносятся только из YouTube Studio; ничего не выдумывается и не скачивается.

Сколько данных нужно: меньше 4 видео с результатами - только список; 4-7 - сравнение
предварительно; от 8 - на него можно опираться. Формула, у которой меньше 3 видео, - мало данных.

Файл: ~/.claude/yt-studio/journal.jsonl (по строке на видео). Другой путь: --file.
"""
import datetime, json, os, re, statistics, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import guard, usage, parse_args, HOME_DIR, die, human_number, classify

MIN_COMPARE, MIN_SOLID, MIN_FORMULA = 4, 8, 3
TEXT = {"--title": "title", "--thumb": "thumb", "--hook": "hook", "--formula": "formula",
        "--title-formula": "title_formula", "--url": "url", "--note": "note"}
NUMS = ("--views", "--ctr", "--avp")
KEYS = ("id", "date", "title", "thumb", "hook", "formula", "title_formula", "url", "views", "ctr", "avp", "note", "auto")

def load(path):
    if not os.path.exists(path): return []
    rows = []
    for n, l in enumerate(open(path, encoding="utf-8"), 1):
        if not l.strip(): continue
        try: rows.append(json.loads(l))
        except ValueError: die(f"{path}: строка {n} испорчена - поправь или удали её, остальные записи целы")
        if not isinstance(rows[-1], dict) or not isinstance(rows[-1].get("id"), int) or "title" not in rows[-1]:
            die(f"{path}: строка {n} не похожа на запись журнала (нет id или title) - поправь или удали её")
    return rows

def save(path, rows):
    # Сначала во временный файл в той же папке, потом замена: если запись оборвётся на середине,
    # старый журнал останется целым.
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".journal-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp): os.remove(tmp)
        raise

# ---------------------------------------------------------------- разбор ввода

def parse_date(s):
    iso, ru = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s.strip()), re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s.strip())
    d = iso.groups() if iso else ru.groups()[::-1] if ru else None
    try: return datetime.date(*[int(x) for x in d]).isoformat()
    except (TypeError, ValueError): die(f"--date: нужна дата вида 2026-09-30 или 30.09.2026, а получено '{s}'")

def parse_num(opt, flag):
    raw = opt[flag]
    v = human_number(raw)
    if v is None: die(f"{flag}: нужно число, а получено '{raw}'")
    if flag == "--views":
        if abs(v - round(v)) > 1e-6: die(f"--views: просмотры - целое число, а получено '{raw}'")
        return int(round(v))
    if v > 100: die(f"{flag}: процент должен быть от 0 до 100, а получено '{raw}'")
    if flag == "--ctr" and v > 30:
        die(f"--ctr: CTR {pct(v)} почти наверняка ошибка - перепроверь '{raw}': не попали ли сюда просмотры или "
            f"процент просмотра")
    return round(v, 2)

def set_numbers(row, opt):
    for flag in NUMS:
        if flag in opt: row[flag[2:]] = parse_num(opt, flag)

def autofill(row, changed):
    """Формулы, которых автор не назвал, определяем по словам. Названное автором не трогаем;
    определённое автоматически пересчитываем, когда меняется сам текст."""
    said, auto = [], set(row.get("auto") or [])
    for key, src, label in (("formula", "hook", "формула определена по словам хука"),
                            ("title_formula", "title", "форма заголовка определена по словам заголовка")):
        if key in changed: auto.discard(key); continue
        if src not in changed or not (key in auto or not row.get(key)): continue
        name = classify(row[src])[0] if row.get(src) else "не определена"
        if name == "не определена":
            row[key] = None; auto.discard(key)
            if src == "hook" and row.get("hook"):
                said.append(f"формула хука по словам не определилась - можно назвать самому: edit {row['id']} --formula ...")
        else:
            row[key] = name; auto.add(key); said.append(f"{label}: {name}")
    row["auto"] = sorted(auto)
    return said

# ---------------------------------------------------------------- вывод

def num(v):
    """8400 -> '8 400': запятая между тысячами по-русски читается как десятичная."""
    return "-" if v is None else f"{int(round(v)):,}".replace(",", " ")

def dec(v, nd=1):
    return f"{v:.{nd}f}".replace(".", ",")

def pct(v):
    return "-" if v is None else f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "%"

def ru_date(iso):
    try: return datetime.date.fromisoformat(iso).strftime("%d.%m.%Y")
    except (TypeError, ValueError): return str(iso or "-")

def cut(s, n):
    s = s or "-"
    return (s if len(s) <= n else s[:n - 1] + "…").ljust(n)

def clean(row):
    return dict({k: row.get(k) for k in KEYS}, auto=row.get("auto") or [])

def table(rows, mult=None, fkey=None):
    head = ("  кратное" if mult else "") + f"  {'#':<4} {'дата':<10}  {cut('заголовок', 40)}  {cut('текст обложки', 20)}  " \
           f"{'просмотры':>10}  {'CTR':>6}  {'досмотр':>7}" + ("  формула" if fkey else "")
    print(head)
    for r in rows:
        m = mult.get(r["id"]) if mult else None
        lead = ("  " + (dec(m, 2) + "x" if m is not None else "-").rjust(7)) if mult else ""
        print(f"{lead}  {'#' + str(r['id']):<4} {ru_date(r.get('date')):<10}  {cut(r['title'], 40)}  {cut(r.get('thumb'), 20)}  "
              f"{num(r.get('views')):>10}  {pct(r.get('ctr')):>6}  {pct(r.get('avp')):>7}"
              + (f"  {r.get(fkey) or '-'}" if fkey else ""))

def analyse(rows):
    done = [r for r in rows if r.get("views") is not None]
    n = len(done)
    out = {"with_results": n, "total": len(rows), "enough_data": n >= MIN_COMPARE,
           "preliminary": MIN_COMPARE <= n < MIN_SOLID, "need_more": max(0, MIN_COMPARE - n),
           "need_more_for_solid": max(0, MIN_SOLID - n), "median": None, "formula_kind": None, "formulas": []}
    med = statistics.median(r["views"] for r in done) if out["enough_data"] else None
    mult = {r["id"]: (round(r["views"] / med, 2) if med else None) for r in done} if out["enough_data"] else {}
    out["entries"] = [dict(clean(r), multiple=mult.get(r["id"])) for r in rows]
    if not out["enough_data"]: return out, mult, None
    out["median"] = med
    # Хук записан хотя бы у одного видео - сравниваем формулы хука; иначе остаётся форма заголовка.
    fkey = "formula" if any(r.get("formula") for r in done) else "title_formula"
    out["formula_kind"] = "hook" if fkey == "formula" else "title"
    by = {}
    for r in done: by.setdefault(r.get(fkey) or "не указана", []).append(r)
    for f, g in by.items():
        ctr = [x["ctr"] for x in g if x.get("ctr") is not None]
        gm = statistics.median(x["views"] for x in g)
        out["formulas"].append({"name": f, "n": len(g), "median": gm, "multiple": round(gm / med, 2) if med else None,
                                "ctr": round(statistics.mean(ctr), 2) if ctr else None, "few_data": len(g) < MIN_FORMULA})
    out["formulas"].sort(key=lambda x: -x["median"])
    return out, mult, fkey

def report(rows, as_json):
    a, mult, fkey = analyse(rows)
    if as_json: print(json.dumps(a, ensure_ascii=False, indent=1)); return
    if not rows: print("  журнал пуст"); return
    n = a["with_results"]
    if not a["enough_data"]:
        print(f"\n  в журнале {a['total']} видео, с результатами {n}\n")
        table(rows)
        print(f"\n  Пока это только список: сравнение начинается с {MIN_COMPARE} видео с результатами - не хватает ещё "
              f"{a['need_more']}.\n  Их можно не ждать: внеси цифры уже вышедших видео (add ... --views ... --ctr ... --avp ...).\n")
        return
    label = f"предварительно: видео с результатами меньше {MIN_SOLID}, выводы могут поменяться" if a["preliminary"] \
        else "данных достаточно, чтобы на сравнение опираться"
    print(f"\n  {n} видео с результатами, медиана {num(a['median'])} просмотров - {label}\n")
    table(sorted(rows, key=lambda r: -(r["views"] if r.get("views") is not None else -1)), mult, fkey)
    kind = "по формулам хука (первая фраза видео)" if fkey == "formula" \
        else "по форме заголовка (хук не записан ни у одного видео)"
    print(f"\n  {kind}" + (" - предварительно" if a["preliminary"] else ""))
    for f in a["formulas"]:
        m = (dec(f["multiple"], 2) + "x") if f["multiple"] is not None else "-"
        print(f"  {m:>7}  {f['n']} видео  {f['name']:<24}" + (f" CTR {pct(round(f['ctr'], 1))}" if f["ctr"] is not None else "")
              + ("   мало данных" if f["few_data"] else ""))
    if any(f["few_data"] for f in a["formulas"]):
        print(f"\n  «мало данных» - у формулы меньше {MIN_FORMULA} видео: это может быть совпадение, а не закономерность.")
    print()

def find(rows, pos, cmd):
    ident = pos[0].lstrip("#") if pos else ""
    if not ident.isdigit(): die(f"{cmd}: нужен номер видео, например: {cmd} 3 " + ("--views 12400" if cmd == "result" else "--hook \"...\""))
    row = next((r for r in rows if r["id"] == int(ident)), None)
    if not row: die(f"нет видео #{ident}" + (" - журнал пуст" if not rows else f"; есть #{rows[0]['id']}-#{rows[-1]['id']}, смотри list"))
    return row

def results_line(row):
    got = [f"{num(row['views'])} просмотров" if row.get("views") is not None else "",
           f"CTR {pct(row['ctr'])}" if row.get("ctr") is not None else "",
           f"средний процент просмотра {pct(row['avp'])}" if row.get("avp") is not None else ""]
    return ", ".join(x for x in got if x)

def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"): usage(__doc__)
    cmd, rest = argv[0], argv[1:]
    pos, opt = parse_args(rest, flags=("--json",), options=tuple(TEXT) + NUMS + ("--date", "--file"))
    as_json = "--json" in opt
    path = opt.get("--file") or os.path.join(HOME_DIR, "journal.jsonl")
    if cmd not in ("add", "result", "edit", "list", "report"):
        die(f"неизвестная команда '{cmd}': есть add, result, edit, list, report (запуск без аргументов - справка)")
    rows = load(path)
    texts = {TEXT[f]: (opt[f].strip() or None) for f in TEXT if f in opt}
    if cmd == "add":
        if not texts.get("title"): die("add: нужен --title - заголовок видео")
        row = {"id": max([r["id"] for r in rows] + [0]) + 1,
               "date": parse_date(opt["--date"]) if "--date" in opt else datetime.date.today().isoformat()}
        row.update({k: texts.get(k) for k in TEXT.values()})
        set_numbers(row, opt)
        said = autofill(row, {k for k, v in texts.items() if v} | {"title"})
        save(path, rows + [row])
        if as_json: print(json.dumps(row, ensure_ascii=False)); return
        hint = "изменить" if "--date" in opt else "это сегодня; если видео вышло в другой день"
        print(f"записано: #{row['id']} «{row['title']}», дата публикации {ru_date(row['date'])} ({hint}: edit {row['id']} --date ДД.ММ.ГГГГ)")
        if results_line(row): print(f"  результаты: {results_line(row)}")
        for s in said: print("  " + s)
    elif cmd == "result":
        row = find(rows, pos, cmd)
        if not any(f in opt for f in NUMS + ("--note",)): die("result: нужна хотя бы одна цифра: --views, --ctr или --avp")
        set_numbers(row, opt)
        if "note" in texts: row["note"] = texts["note"]
        save(path, rows)
        if as_json: print(json.dumps(row, ensure_ascii=False)); return
        print(f"обновлено: #{row['id']} «{row['title']}» - {results_line(row) or 'цифр пока нет'}")
    elif cmd == "edit":
        row = find(rows, pos, cmd)
        if any(f in opt for f in NUMS): die("edit: цифры меняются через result, например: result %d --views 12400" % row["id"])
        if not texts and "--date" not in opt: die("edit: укажи, что поменять: --title, --thumb, --hook, --formula, --title-formula, --url, --date, --note")
        if "title" in texts and not texts["title"]: die("edit: --title не может быть пустым")
        if "--date" in opt: row["date"] = parse_date(opt["--date"])
        row.update(texts)
        said = autofill(row, set(texts))
        save(path, rows)
        if as_json: print(json.dumps(row, ensure_ascii=False)); return
        names = {"title": "заголовок", "thumb": "текст обложки", "hook": "хук", "formula": "формула хука",
                 "title_formula": "форма заголовка", "url": "ссылка", "note": "заметка"}
        what = [names[k] for k in texts] + (["дата публикации " + ru_date(row["date"])] if "--date" in opt else [])
        print(f"изменено: #{row['id']} «{row['title']}» - " + ", ".join(what))
        print("  теперь: " + "; ".join(f"{k}: {v}" for k, v in row.items() if k in ("date", "thumb", "hook", "formula", "title_formula", "url", "note") and v))
        for s in said: print("  " + s)
    elif cmd == "list":
        if as_json: print(json.dumps([clean(r) for r in rows], ensure_ascii=False, indent=1)); return
        if not rows: print("  журнал пуст"); return
        table(rows)
    else: report(rows, as_json)

if __name__ == "__main__":
    guard(main)
