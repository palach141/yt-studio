#!/usr/bin/env python3
"""retention.py - чтение выгрузки удержания аудитории из YouTube Studio.

    python3 retention.py retention.csv --duration 10:00
    python3 retention.py retention.csv --duration 600 --transcript transcript.srt
    python3 retention.py retention.csv --json

Файл: Studio -> видео -> Аналитика -> расширенный режим -> показатель "Удержание аудитории" ->
экспорт. Нужны два столбца: позиция в видео (проценты, доли, секунды или м:сс) и процент
смотрящих. Если столбцов с процентами несколько, берётся "абсолютное" удержание; какой столбец
взят, написано в первой строке вывода. Там же шаг данных: точнее него момент назвать нельзя.

Четыре разные вещи с разными лечениями:
  ХУК      сколько ушло за первые 30 секунд (у видео короче минуты - за первые 20%), и отдельно -
           сколько из этого за первые 5 секунд. Если больше половины там, дело в первой фразе и
           первом кадре, а не в затянутом вступлении
  ОБРЫВЫ   отдельные резкие падения после хука - конкретный момент, на котором ушли
  ВСПЛЕСКИ места, где кривая растёт: их пересматривают. Это кандидаты в Shorts
  СКЛОН    ровная потеря в середине: всего пунктов от конца окна хука до конца видео без обрывов и
           всплесков, и в пересчёте на минуту (для видео от 3 минут)

Все потери - в процентных пунктах от всех начавших смотреть, округление одинаковое в тексте и
в --json. Норм и порогов "хорошо/плохо" тут нет: сравнивать нужно со своими же видео.

Без --duration ось в процентах нельзя перевести в секунды: обрывы будут названы в % видео, а
--transcript не сработает. С --transcript печатается: для хука - что звучало в первые 5 секунд;
для обрыва - 8 секунд ПЕРЕД ним (уходят в ответ на уже сказанное); для всплеска - от 1 секунды до
и 8 секунд ПОСЛЕ его начала (пересматривают то, что звучит в этом месте и дальше).
"""
import csv, json, os, statistics, sys
from decimal import Decimal, ROUND_HALF_UP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import guard, usage, duration, read_text, parse_args, load_transcript, parse_ts, fmt_ts, die

KEYS = ("absolute", "абсолют", "audiencewatchratio", "watch ratio")    # заголовок нужного столбца

def r1(v, nd=1):
    """Округление половины вверх: round() в Python банковское (6.25 -> 6.2), а зритель ждёт 6.3.
    Сначала срезается шум float, иначе 6.25 после вычитаний оказывается 6.2499999."""
    return float(Decimal(repr(round(v, 6))).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)) + 0.0

def num(c):
    c = c.strip().replace("%", "").replace(" ", "").replace(" ", "")
    if ":" in c:
        try: return parse_ts(c)
        except ValueError: return None
    if c.count(",") == 1 and "." not in c: c = c.replace(",", ".")    # 45,3 -> 45.3
    try: return float(c.replace(",", ""))
    except ValueError: return None

def load_csv(path):
    """-> (точки [(позиция, процент)], заголовок взятого столбца или None, позиции заданы как м:сс)."""
    lines = [l for l in read_text(path).splitlines() if l.strip()]
    # разделитель - тот, что есть в каждой строке: счёт "чего больше" ломается на десятичных запятых (0,5;99,5)
    delim = next((d for d in ("\t", ";") if lines and all(d in l for l in lines[:5])), ",")
    try: table = [r for r in csv.reader(lines, delimiter=delim) if r]
    except csv.Error: table = []
    header = next((r for r in table if sum(num(c) is None for c in r) == len(r)), None)
    ycol = 1
    if header:
        for i, h in enumerate(header):
            if i and any(k in h.lower() for k in KEYS): ycol = i; break
    rows, clock = [], False
    for r in table:
        if len(r) > ycol and num(r[0]) is not None and num(r[ycol]) is not None:
            rows.append((num(r[0]), num(r[ycol]))); clock = clock or ":" in r[0]
    rows.sort()
    if rows and max(y for _, y in rows) <= 2.0: rows = [(x, y * 100) for x, y in rows]   # доли -> проценты
    if rows and not clock and rows[-1][0] <= 1.0: rows = [(x * 100, y) for x, y in rows]  # позиция долей 0..1
    column = header[ycol].strip() if header and len(header) > ycol and header[ycol].strip() else None
    return rows, column, clock

def clip(text, n=160, tail=False):
    """Обрезка до n знаков по границе слова. tail=True оставляет конец: перед обрывом важнее последнее сказанное."""
    text = " ".join(text.split())
    if len(text) <= n: return text
    if tail:
        cut = text[-n:]
        if text[-n - 1] != " " and " " in cut: cut = cut.split(" ", 1)[1]
        return "…" + cut.lstrip()
    cut = text[:n]
    if text[n] != " " and " " in cut: cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"

def analyse(rows, dur, clock=False):
    xs, ys = [r[0] for r in rows], [r[1] for r in rows]
    # ось в процентах, если значения укладываются в 0-100 и при этом не совпадают с длиной в секундах
    pct_axis = not clock and max(xs) <= 100.5 and not (dur is not None and dur < 99 and abs(max(xs) - dur) <= 1.0)
    guess = pct_axis and dur is None and max(xs) < 99      # не дотягивает до 100: возможно, это секунды
    if not pct_axis and dur is None: dur = max(xs)
    have_sec = dur is not None
    k = (dur / 100.0 if pct_axis else 1.0) if have_sec else None      # секунд в единице оси
    sec = (lambda x: x * k) if have_sec else (lambda x: None)
    def at(x):                                             # значение кривой в произвольной позиции
        if x <= xs[0]: return ys[0]
        for i in range(1, len(xs)):
            if x <= xs[i]:
                return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / ((xs[i] - xs[i - 1]) or 1)
        return ys[-1]
    cutoff = 30.0 / k if have_sec else 10.0
    short = cutoff > max(xs) * 0.5                         # у Shorts 30 секунд - это полвидео
    if short: cutoff = max(xs) * 0.2
    step = statistics.median(xs[i] - xs[i - 1] for i in range(1, len(xs)))
    start, leak = ys[0], ys[0] - at(cutoff)
    # первый срез хука: 5 секунд (5% видео без секунд), но не больше половины окна - у Shorts окно само короткое
    f_end = min(5.0 / k, cutoff / 2) if have_sec else 5.0
    if not any(xs[0] < x <= f_end + 1e-9 for x in xs):     # точек внутри среза нет: берём первую точку,
        f_end = xs[1] if xs[1] <= cutoff / 2 + 1e-9 else None   # если она ещё отделима от остального окна
    first = None
    if f_end is not None:
        fs = r1(sec(f_end)) if have_sec else None
        first = {"window": ("первые 5 секунд" if fs == 5 else f"первые {fs:g} с") if have_sec else f"первые {r1(f_end):g}% видео",
                 "seconds": fs, "lost": r1(start - at(f_end))}
    steps = [(xs[i - 1], xs[i], ys[i - 1] - ys[i]) for i in range(1, len(rows))]
    mid = [s for s in steps if s[0] >= cutoff]
    rates = [d / ((b - a) or 1) for a, b, d in mid]
    typical = statistics.median(rates) if rates else 0
    # обрыв: шаг после хука, где теряется заметно больше обычного (втрое от медианы и не меньше 1 пункта)
    cliffs, bumps, out_d, out_x = [], [], 0.0, 0.0
    for (a, b, d), r in zip(mid, rates):
        cliff = d >= 1.0 and r >= 3 * max(typical, 1e-9)
        if not cliff and d > -0.5: continue
        out_d += d; out_x += b - a                         # эти шаги в склон не входят
        lst, key = (cliffs, "lost") if cliff else (bumps, "gain")
        if lst and abs(lst[-1]["to"] - a) < 1e-9: lst[-1]["to"] = b; lst[-1][key] += abs(d)
        else: lst.append({"from": a, "to": b, key: abs(d)})
    cliffs = sorted(cliffs, key=lambda c: -c["lost"])[:5]; bumps = sorted(bumps, key=lambda c: -c["gain"])[:5]
    for c in cliffs + bumps:
        t = sec(c["from"])
        c["at_seconds"] = r1(t) if have_sec else None
        c["at"] = fmt_ts(int(t + 0.5)) if have_sec else None    # до ближайшей секунды: 56.6 -> 0:57
        for key in ("from", "to"): c[key] = round(c[key], 2)
        for key in ("lost", "gain"):
            if key in c: c[key] = r1(c[key])
    slide = at(cutoff) - ys[-1] - out_d
    span = max(xs) - cutoff - out_x
    per_min = slide / (span * k) * 60.0 if have_sec and span > 0 else None
    is_short = have_sec and dur < 180                      # на коротком видео "в минуту" - экстраполяция дальше самого видео
    area = sum((xs[i] - xs[i - 1]) * (ys[i] + ys[i - 1]) / 2 for i in range(1, len(rows)))
    avg = area / (xs[-1] - xs[0]) if xs[-1] > xs[0] else ys[0]
    ws = sec(cutoff)
    lk = r1(leak)
    return {"points": len(rows), "axis": "percent" if pct_axis else "seconds", "axis_guessed": guess, "duration": dur,
            "step_seconds": r1(sec(step)) if have_sec else None, "step_percent": r1(step) if pct_axis else None,
            "start": r1(start), "end": r1(ys[-1]), "peak": r1(max(ys)), "avg_viewed_pct": r1(avg),
            "hook_window": ("30 секунд" if not short else f"первые {r1(ws):g} с") if have_sec else f"первые {cutoff:.0f}% видео",
            "hook_window_seconds": r1(ws) if have_sec else None, "hook_leak": lk,
            "hook_approx": step > cutoff,                  # точки реже окна хука: потеря за окно - интерполяция
            "hook_first": first, "hook_rest": r1(lk - first["lost"]) if first else None,
            "hook_front_loaded": bool(first and lk > 0 and first["lost"] > lk / 2),
            "cliffs": cliffs, "bumps": bumps, "slide_total": r1(slide),
            "slide_from": fmt_ts(int(ws + 0.5)) if have_sec else f"{cutoff:.0f}%",
            "slide_to": fmt_ts(int(sec(max(xs)) + 0.5)) if have_sec else f"{max(xs):.0f}%",
            "slide_per_minute": r1(per_min) if per_min is not None and not is_short else None,
            "short_video": bool(is_short)}

def main():
    pos, opt = parse_args(sys.argv[1:], flags=("--json",), options=("--duration", "--transcript"))
    if not pos: usage(__doc__)
    if not os.path.isfile(pos[0]): die(f"нет файла: {pos[0]}")
    rows, column, clock = load_csv(pos[0])
    if len(rows) < 8: die("в файле меньше 8 строк вида 'позиция, процент'. Нужна выгрузка удержания из Studio или\n"
                          "точки, снятые с графика вручную: по строке на точку, например '0:30, 62'")
    dur = duration(opt)
    out = analyse(rows, dur, clock)
    out["column"] = column
    first = out["hook_first"]
    if "--transcript" in opt:
        tr = load_transcript(opt["--transcript"])
        if first and first["seconds"] is not None: first["said"] = clip(tr.text_between(0, first["seconds"]))
        for c in out["cliffs"] + out["bumps"]:
            if c["at_seconds"] is None: continue
            t = c["at_seconds"]
            # обрыв - реакция на уже сказанное; всплеск - пересматривают то, что звучит в точке и после неё
            c["said"] = clip(tr.text_between(t - 8, t + 2), tail=True) if "lost" in c else clip(tr.text_between(t - 1, t + 8))
    if "--json" in opt: print(json.dumps(out, ensure_ascii=False, indent=1)); return
    where = lambda c: c["at"] if c["at"] is not None else f"{c['from']:g}% видео"
    d = lambda v: f"{-v:+.1f}"                              # потеря со знаком: рост в начале печатается плюсом
    said = lambda c, pre="": f'   {pre}"{c["said"]}"' if c.get("said") else ""
    head = f"\n  {pos[0]}   точек: {out['points']}"
    if column: head += f'   столбец: "{column}"'
    if out["step_seconds"] is not None: head += f"   шаг данных: {out['step_seconds']:g} с"
    elif out["step_percent"] is not None: head += f"   шаг данных: {out['step_percent']:g}% видео"
    print(head)
    print(f"  {out['start']}% -> {out['end']}%   в среднем досмотрено {out['avg_viewed_pct']}%\n")
    print(f"  ХУК       {d(out['hook_leak'])} п. за {out['hook_window']}" + ("  (точки реже окна: оценка)" if out["hook_approx"] else ""))
    if first:
        print(f"            из них {d(first['lost'])} п. за {first['window']}, {d(out['hook_rest'])} п. за остаток окна")
        if out["hook_front_loaded"]: print(f"            больше половины - в {first['window']}: это первая фраза и первый кадр")
        if first.get("said"): print(f'            в {first["window"]} звучало: "{first["said"]}"')
    else: print("            точки слишком редкие, чтобы отделить первые секунды от остального окна")
    if out["peak"] > 100: print(f"            кривая поднимается до {out['peak']}%: выше 100 бывает, когда начало пересматривают")
    print("            нормы нет: сравнивай со своими же видео той же длины\n")
    print("  ОБРЫВЫ    моменты после хука, где ушло заметно больше обычного")
    for c in out["cliffs"]: print(f"    {d(c['lost']):>6} п.  на {where(c):>10}" + said(c, "перед этим: "))
    if not out["cliffs"]: print("    нет - потери ровные, это склон, а не моменты")
    print("\n  ВСПЛЕСКИ  кривая растёт: это пересматривают")
    for c in out["bumps"]: print(f"    {d(-c['gain']):>6} п.  на {where(c):>10}" + said(c, "здесь и дальше: "))
    if not out["bumps"]: print("    нет")
    line = f"\n  СКЛОН     {d(out['slide_total'])} п. за середину ({out['slide_from']} - {out['slide_to']}, без обрывов и всплесков)"
    if out["slide_per_minute"] is not None: line += f", это {d(out['slide_per_minute'])} п. в минуту"
    print(line)
    if out["short_video"]: print("            на коротком видео пересчёт в минуту не показателен")
    elif out["slide_per_minute"] is None: print("            дай --duration, чтобы пересчитать в минуту")
    if dur is None and out["axis"] == "percent":
        print("\n  ! длина видео не задана: позиции в процентах, текст из транскрипта не подставлен")
        if out["axis_guessed"]: print("  ! позиции не доходят до 100: считаю их процентами видео. Если это секунды - дай --duration")
    print()

if __name__ == "__main__":
    guard(main)
