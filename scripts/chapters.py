#!/usr/bin/env python3
"""chapters.py - главы YouTube: черновик из транскрипта и проверка готового блока.

    python3 chapters.py transcript.srt                     # черновик границ, число глав - по длине видео
    python3 chapters.py transcript.srt --target 8          # то же, но глав не больше 8
    python3 chapters.py transcript.srt --cuts cuts.json    # метки для ВЫРЕЗАННОЙ версии (cuts.py --json > cuts.json)
    python3 chapters.py --check chapters.txt --duration 12:40   # проверка того, что пойдёт в описание

Правила YouTube, при нарушении которых блок молча не становится главами: первая метка 0:00,
минимум три метки, по возрастанию, каждая глава не короче 10 секунд.

Черновик находит ГРАНИЦЫ: паузы между фразами плюс смена словаря вокруг них. Он скорее делит лишнее,
чем пропускает: границу, которая режет одну тему, удаляй. Названия в черновике - частые слова
раздела, а не заголовки; их надо переписать. После переписывания прогони --check: проверять нужно
тот блок, который реально вставляется в описание, а не черновик.

Без --target число глав выбирается по длине: 3 на совсем коротком видео, до 10 на длинном.

--cuts: если видео публикуется после реза по cuts.py, метки по исходному транскрипту опаздывают.
С --cuts границы ищутся по исходнику, а время каждой пересчитывается на вырезанную версию. Граница
внутри вырезанного куска встаёт на начало следующего оставленного; если после пересчёта глава
вышла короче 10 секунд, её метка убирается. --duration для --check тогда - длина вырезанной версии.
"""
import json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import guard, usage, number, duration as get_duration, tokens, content_words, stem, parse_args, load_transcript, parse_ts, fmt_ts, read_text, remap, die

MIN = 10.0

def validate(starts, duration=None):
    errs = []
    if len(starts) < 3: errs.append(f"меток: {len(starts)} - нужно минимум 3")
    if starts and starts[0] != 0: errs.append("первая метка должна быть 0:00")
    for i in range(1, len(starts)):
        if starts[i] <= starts[i - 1]: errs.append(f"метка {fmt_ts(starts[i])} идёт не по возрастанию")
        elif starts[i] - starts[i - 1] < MIN: errs.append(f"глава с {fmt_ts(starts[i - 1])} короче 10 секунд")
    if duration is not None and starts:
        if starts[-1] >= duration: errs.append(f"метка {fmt_ts(starts[-1])} за пределами видео")
        elif duration - starts[-1] < MIN: errs.append("последняя глава короче 10 секунд")
    return errs

def check_block(path, duration):
    rows = []
    for line in read_text(path).splitlines():
        m = re.match(r"\s*[-–(\[]?\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s*[)\]]?\s*[-–—:]?\s*(.*)", line)
        if m: rows.append((parse_ts(m.group(1)), m.group(2).strip()))
    errs = validate([r[0] for r in rows], duration)
    for t, title in rows:
        if not title: errs.append(f"у метки {fmt_ts(t)} нет названия")
        elif len(title.split()) > 6: errs.append(f'"{title}" - длинно; глава должна называться в 3-5 слов')
    return rows, errs

def auto_target(dur):
    return max(3, min(10, int(round(dur / 75.0)) + 3))

def boundaries(tr, target):
    """Начала глав по времени исходника."""
    segs, dur = tr.segs, tr.duration
    min_len = max(MIN, dur / (target * 3))           # на длинном видео главы по 10 секунд не нужны
    cand, prev = [], tokens(segs[0][2])
    for i in range(1, len(segs)):
        tk = tokens(segs[i][2])
        if len(tk) < 3: continue                        # "э-э" и обрывки главу не открывают
        retake, prev = len(prev) >= 3 and tk[:3] == prev[:3], tk
        if retake: continue                             # пересказ фальстарта - та же мысль, а не новая тема
        gap = min(3.0, max(0.0, segs[i][0] - segs[i - 1][1]))
        kb = {stem(w) for s in segs[max(0, i - 12):i] for w in content_words(s[2], 4)}
        ka = {stem(w) for s in segs[i:i + 12] for w in content_words(s[2], 4)}
        shift = 1 - len(kb & ka) / len(kb | ka) if (kb | ka) else 0
        cand.append((gap + shift * 3.0, segs[i][0]))
    picked = [0.0]
    for _, t in sorted(cand, key=lambda c: (-c[0], c[1])):
        if len(picked) >= target: break
        if all(abs(t - p) >= min_len for p in picked) and dur - t >= min_len: picked.append(t)
    return sorted(picked)

def describe(segs, starts, dur):
    out = []
    for n, t in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else dur
        freq, form = {}, {}
        for s in segs:
            if s[0] >= t and s[0] < end:
                for w in content_words(s[2], 4):
                    k = stem(w); freq[k] = freq.get(k, 0) + 1; form.setdefault(k, w)
        top = [form[k] for k in sorted(freq, key=lambda k: (-freq[k], k))[:3]]   # порядок детерминированный
        first = next((s[2] for s in segs if s[0] >= t), "")
        out.append({"start": round(t, 2), "label": fmt_ts(t), "draft_title": " ".join(top) or "раздел",
                    "first_line": first[:70], "seconds": round(end - t, 2)})
    return out

def load_cuts(path):
    """Файл от cuts.py --json -> (оставленные куски, длина после реза)."""
    if not os.path.isfile(path): die(f"нет файла: {path}")
    bad = f"--cuts: {path} не похож на вывод cuts.py --json (нужен ключ keep: пары [начало, конец])"
    try:
        d = json.loads(read_text(path))
        keep = [(float(a), float(b)) for a, b in d["keep"]]
        out = float(d["out"]) if d.get("out") is not None else sum(b - a for a, b in keep)
    except (ValueError, KeyError, TypeError): die(bad)
    if not keep or out <= 0 or any(b <= a for a, b in keep) or any(keep[i][0] < keep[i - 1][1] for i in range(1, len(keep))): die(bad)
    return keep, out

def to_cut(segs, starts, keep, out):
    """Фразы и границы на шкале вырезанной версии; dropped - метки, для которых главы не осталось."""
    # Дрожание float при пересчёте не должно увести 0:00 и стыки кусков на сотые в сторону
    m = lambda t: round(remap(t, keep), 2)
    segs2 = [(m(s[0]), m(s[1]), s[2]) for s in segs if m(s[1]) - m(s[0]) > 0.05]   # вырезанные фразы в названия не идут
    starts2, dropped = [0.0], []
    for t in starts[1:]:
        c = m(t)
        if c - starts2[-1] < MIN or out - c < MIN: dropped.append({"source": fmt_ts(t), "label": fmt_ts(c)})
        else: starts2.append(c)
    return segs2, starts2, dropped

def main():
    pos, opt = parse_args(sys.argv[1:], flags=("--json",), options=("--target", "--check", "--duration", "--cuts"))
    duration = get_duration(opt)
    if "--check" in opt:
        if not os.path.isfile(opt["--check"]): die(f"нет файла: {opt['--check']}")
        rows, errs = check_block(opt["--check"], duration)
        notes = [] if duration is not None else ["длина видео не задана --duration: последняя глава не проверена"]
        if "--json" in opt:
            print(json.dumps({"valid": not errs, "complete": not notes, "count": len(rows), "errors": errs, "notes": notes},
                             ensure_ascii=False, indent=1))
        else:
            head = "НЕ СТАНЕТ ГЛАВАМИ" if errs else "ГОДИТСЯ - YouTube покажет главы" if not notes else \
                   "ПРАВИЛА СОБЛЮДЕНЫ, но последняя глава не проверена: дай --duration"
            print(f"\n  меток: {len(rows)} - {head}")
            for e in errs: print(f"    x  {e}")
            for e in notes: print(f"    !  {e}")
            print()
        sys.exit(2 if errs else 0)
    if not pos: usage(__doc__)
    tr = load_transcript(pos[0])
    if len(tr.segs) < 6: die("слишком мало реплик, чтобы делить на главы")
    keep = load_cuts(opt["--cuts"]) if "--cuts" in opt else None
    auto = "--target" not in opt
    target = auto_target(tr.duration) if auto else int(number(opt, "--target", 7, 3))
    segs, starts, dur, dropped = tr.segs, boundaries(tr, target), tr.duration, []
    if keep:
        keep, dur = keep
        segs, starts, dropped = to_cut(segs, starts, keep, dur)
    ch = describe(segs, starts, dur)
    errs = validate([c["start"] for c in ch], dur)
    if "--json" in opt:
        print(json.dumps({"valid": not errs, "errors": errs, "target": target, "auto_target": auto,
                          "timeline": "cut" if keep else "source", "duration": round(dur, 2), "dropped": dropped,
                          "chapters": ch}, ensure_ascii=False, indent=1)); return
    print()
    if keep: print(f"  ВРЕМЯ - ДЛЯ ВЫРЕЗАННОЙ ВЕРСИИ (длина {fmt_ts(dur + 0.5)}, исходник {fmt_ts(tr.duration + 0.5)}). К исходнику эти метки не подходят.\n")
    for c in ch: print(f"  {c['label']:>7}  [{c['draft_title']}]   начинается с: \"{c['first_line']}\"")
    print(f"\n  глав: {len(ch)}" + ("" if not errs else "  -- НЕ ГОДИТСЯ: " + "; ".join(errs)))
    for x in dropped:
        print(f"  ! граница {x['source']} исходника убрана: после реза она встаёт на {x['label']}, и глава вышла бы короче 10 секунд")
    print(f"  Глав не больше {target}: " + ("число выбрано по длине видео, меняется через --target N." if auto else "так задано в --target."))
    print("  В скобках - частые слова раздела, не названия. Перепиши каждое и проверь блок через --check"
          + (f" --duration {fmt_ts(dur)} (длина после реза).\n" if keep else ".\n"))

if __name__ == "__main__":
    guard(main)
