#!/usr/bin/env python3
"""outliers.py - какие видео в нише обогнали СВОЙ канал, и во сколько раз.

    python3 outliers.py channel1.json channel2.json --min 2.0
    python3 outliers.py мой_список.txt --channel "Бег с нуля"
    python3 outliers.py collected.json --json

Вход - один или несколько файлов, форматы можно смешивать:
  1. дамп yt-dlp:   yt-dlp --flat-playlist -J "https://www.youtube.com/@канал/videos" > channel1.json
  2. свой список:   [{"channel":"...","title":"...","views":412000,"url":"...","duration":613}, ...]
                    обязательны title и views; views можно писать как "310 тыс" или "1.2M".
                    Без duration и ссылки на /shorts/ видео считается длинным ("short": true - пометить Shorts).
  3. текст (.txt):  одно видео на строку, "название — просмотры":
                        # Бег с нуля
                        Как я пробежал марафон без подготовки — 310 тыс
                        5 ошибок новичка в беге - 41 тыс
                        Разминка за минуту; 12к [short]
                    Между названием и просмотрами - " — ", " - ", табуляция или ";" (берётся ПОСЛЕДНИЙ
                    разделитель в строке, так что тире в названии не мешает). Имя канала - строка
                    "# Название" (можно несколько каналов в одном файле), иначе --channel, иначе имя файла.
                    [short] или [шортс] в конце строки помечает Shorts.

Просмотры ранжируют размер канала, а не идею. Поэтому каждое видео оценивается как КРАТНОЕ МЕДИАНЫ
своего канала. Три поправки, без которых это число врёт:
  - медиана считается БЕЗ самого видео (иначе выброс сам подтягивает свою базу);
  - Shorts и длинные сравниваются отдельно: у них разные порядки просмотров;
  - база - последние --recent видео (по умолчанию 30), а не вся история канала.
    "Последние" - это первые в файле: инструмент считает, что список идёт ОТ НОВЫХ К СТАРЫМ, как
    у yt-dlp. В списке, набранном руками, держи тот же порядок (важно, если видео больше --recent).
В группе нужно минимум 5 видео, иначе она пропускается, и об этом будет сказано.

Если в данных есть дата публикации, видео моложе --min-age дней (по умолчанию 7) помечаются как
"ещё растёт" - их кратное занижено. В режиме --flat-playlist дат обычно нет; тогда пометки нет.

Формула определяется по ЗАГОЛОВКУ. Это суждение о словах, а не объяснение, почему видео зашло.
После списка печатается блок "насколько этому верить" - только те оговорки, что относятся к этим данным.
"""
import datetime, json, os, re, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import guard, usage, number, parse_args, read_text, classify, load_formulas, die, human_number

MIN_GROUP, SMALL_GROUP, MIN_CHANNELS = 5, 10, 3
# Дефис - разделитель только с пробелами по бокам: в названиях он бывает и внутри слов.
SEP = re.compile(r"\s*[—–]\s*|\s+-\s+|\t+|\s*;\s*")
MARK = re.compile(r"^\s*\[(shorts?|шортс?)\]\s*|\s*\[(shorts?|шортс?)\]\s*$", re.I)

class BadInput(Exception): pass

def flatten(d, channel=None):
    """Дамп yt-dlp может быть вложенным: канал -> вкладки (Videos, Shorts) -> ролики."""
    if isinstance(d, list):
        for x in d: yield from flatten(x, channel)
        return
    if not isinstance(d, dict): return
    if isinstance(d.get("videos"), list):
        yield from flatten(d["videos"], channel); return
    ch = d.get("channel") or d.get("uploader") or channel
    if isinstance(d.get("entries"), list):
        for e in d["entries"]: yield from flatten(e, ch)
        return
    views = d.get("views", d.get("view_count"))
    if views is None or not d.get("title"): return
    n = None if isinstance(views, bool) else float(views) if isinstance(views, (int, float)) else human_number(views)
    if n is None:
        raise BadInput(f"у видео «{d['title']}» просмотры не число: {json.dumps(views, ensure_ascii=False)}. "
                       f"Нужно число или запись вида \"310 тыс\"")
    url = d.get("url") or d.get("webpage_url") or (f"https://youtu.be/{d['id']}" if d.get("id") else "")
    dur = d.get("duration")
    date = d.get("upload_date") or d.get("date")
    if not date and d.get("timestamp"):
        date = datetime.datetime.fromtimestamp(d["timestamp"], datetime.timezone.utc).strftime("%Y%m%d")
    short = bool(d.get("short")) or "/shorts/" in url or (isinstance(dur, (int, float)) and dur <= 60)
    yield {"channel": str(ch or "?"), "title": str(d["title"]), "views": n, "url": url, "short": short,
           "known": short or "short" in d or isinstance(dur, (int, float)), "date": str(date or "").replace("-", "")[:8]}

def parse_line(line):
    short = bool(MARK.search(line))
    line = MARK.sub("", line)
    seps = list(SEP.finditer(line))
    if not seps: return None
    title = line[:seps[-1].start()].strip()
    views = human_number(re.sub(r"\s*(просмотр\w*|views?)\.?$", "", line[seps[-1].end():], flags=re.I))
    if not title or views is None: return None
    return {"title": title, "views": views, "url": "", "short": short, "date": ""}

def load_text(raw, channel):
    vids = []
    for n, line in enumerate(raw.splitlines(), 1):
        # маркеры списка и ";" в конце - так списки выглядят, когда их вставляют из чата
        line = re.sub(r"^[-*•]\s+", "", line.strip()).rstrip(";, \t")
        if not line: continue
        v = parse_line(line)
        # "#shorts утро — 5 тыс" - видео с хэштегом, а "# Канал" и "#Канал" без просмотров - имя канала
        if line.startswith("#") and (v is None or line.startswith("# ")):
            channel = line.lstrip("#").strip() or channel; continue
        if v is None:
            raise BadInput(f"строка {n}: не понял «{line[:60]}». Нужно \"название — просмотры\", "
                           f"например: Как я пробежал марафон — 310 тыс")
        vids.append(dict(v, channel=channel))
    # Если автор пометил хоть один Shorts, остальные строки - осознанно длинные; если нет - формат неизвестен.
    marked = any(v["short"] for v in vids)
    for v in vids: v["known"] = marked
    return vids

def load(path, channel):
    if not os.path.exists(path): die(f"нет файла: {path}")
    raw = read_text(path)
    name = channel or os.path.splitext(os.path.basename(path))[0]
    is_text = path.lower().endswith(".txt") or (not path.lower().endswith(".json") and raw.lstrip()[:1] not in ("[", "{"))
    try:
        if is_text: return load_text(raw, name)
        try: data = json.loads(raw)
        except ValueError as ex: die(f"{path}: не json ({ex})")
        return list(flatten(data, name))
    except BadInput as ex:
        die(f"{path}: {ex}" if not is_text else f"{path}, {ex}")

def age_days(date):
    try: return (datetime.date.today() - datetime.datetime.strptime(date, "%Y%m%d").date()).days
    except ValueError: return None

def caveats(used, channels):
    """Оговорки только по тем группам, что вошли в расчёт. used - [(канал, short, видео группы)]."""
    out, vids = [], [v for _, _, g in used for v in g]
    small = [f"{ch} ({'Shorts' if short else 'длинные'}) - {len(g)}" for ch, short, g in used if len(g) < SMALL_GROUP]
    if small:
        out.append(f"мало видео для базы (меньше {SMALL_GROUP}): " + "; ".join(small[:8]) + (" и другие" if len(small) > 8 else "")
                   + ". Одно-два видео сдвигают медиану, кратное здесь приблизительное")
    undated = sum(1 for v in vids if not v["date"])
    if vids and undated == len(vids):
        out.append("в данных нет дат: свежие видео не помечены, а они ещё набирают - их кратное занижено")
    elif undated:
        out.append(f"у {undated} видео из {len(vids)} нет даты: свежие среди них не помечены, их кратное занижено")
    unknown = sum(1 for v in vids if not v["known"])
    if unknown:
        out.append(f"у {unknown} видео нет ни длительности, ни ссылки на /shorts/: все они посчитаны как длинные. "
                   f"Если среди них есть Shorts, база смешана - пометь их ([short] в тексте, \"short\": true в json)")
    if 0 < channels < MIN_CHANNELS:
        out.append(f"каналов в расчёте: {channels}. Это картина " + ("одного канала" if channels == 1 else "пары каналов")
                   + f", а не ниши - для выводов о нише нужно хотя бы {MIN_CHANNELS}, лучше 5-10")
    return out

def main():
    pos, opt = parse_args(sys.argv[1:], flags=("--json",), options=("--min", "--recent", "--min-age", "--channel"))
    if not pos: usage(__doc__)
    lo, recent, min_age = number(opt, "--min", 1.5, 0), int(number(opt, "--recent", 30, 5)), int(number(opt, "--min-age", 7, 0))
    vids = []
    for p in pos: vids += load(p, opt.get("--channel"))
    if not vids: die("в файлах не нашлось видео с числом просмотров. Нужен дамп yt-dlp (fetch.py channel URL),\n"
                     "список вида [{\"channel\":...,\"title\":...,\"views\":...}] или текст: название — просмотры")
    groups = {}
    for v in vids: groups.setdefault((v["channel"], v["short"]), []).append(v)
    formulas, out, thin, used = load_formulas(), [], [], []
    for (ch, short), g in groups.items():
        g = g[:recent]                                   # листинг канала идёт от новых к старым
        if len(g) < MIN_GROUP: thin.append((ch, "Shorts" if short else "длинные", len(g))); continue
        used.append((ch, short, g))
        for i, v in enumerate(g):
            base = statistics.median(x["views"] for j, x in enumerate(g) if j != i)
            age = age_days(v["date"]) if v["date"] else None
            out.append({"channel": ch, "format": "short" if short else "long", "title": v["title"],
                        "views": int(v["views"]), "baseline": int(base),
                        "multiple": round(v["views"] / base, 2) if base else 0.0,
                        "still_growing": age is not None and age < min_age,
                        "formula": classify(v["title"], formulas)[0], "url": v["url"]})
    out = sorted((r for r in out if r["multiple"] >= lo), key=lambda r: -r["multiple"])
    counts = {}
    for r in out: counts[r["formula"]] = counts.get(r["formula"], 0) + 1
    notes = caveats(used, len({ch for ch, _, _ in used}))
    if "--json" in opt:
        print(json.dumps({"videos": len(vids), "outliers": out, "formulas": counts,
                          "skipped_thin": [list(t) for t in thin], "caveats": notes}, ensure_ascii=False, indent=1)); return
    print(f"\n  видео: {len(vids)}, каналов: {len({v['channel'] for v in vids})}, порог {lo:g}x от медианы своего канала\n")
    for r in out[:25]:
        tag = "S" if r["format"] == "short" else " "
        print(f"    {r['multiple']:6.2f}x {tag} {r['views']:>10,} при базе {r['baseline']:>9,}   {r['channel'][:20]:<20} {r['title'][:56]}")
        phrase = next((f.get("user_phrase") for f in formulas if f["name"] == r["formula"]), None)
        print(f"              формула заголовка: {r['formula']}" + (f" - {phrase}" if phrase else "") + ("   (моложе недели, ещё растёт)" if r["still_growing"] else ""))
    if not out: print("    порог никто не прошёл - собери больше видео на канал или снизь --min")
    for ch, kind, n in thin[:8]:
        print(f"\n  пропущено: {ch}, {kind} - всего {n} видео, медиана по такому числу ничего не значит", end="")
    if thin: print()
    if counts:
        print("\n  формулы заголовков среди выбросов (по словам заголовка, не причина успеха)")
        for f, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])): print(f"    {n:2d}  {f}")
    if notes:
        print("\n  насколько этому верить")
        for c in notes: print(f"    - {c}")
    print()

if __name__ == "__main__":
    guard(main)
