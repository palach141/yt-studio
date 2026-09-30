#!/usr/bin/env python3
"""cuts.py - монтажный лист из транскрипта с таймкодами: что вырезать и что останется.

    python3 cuts.py transcript.srt                      # srt, vtt (в т.ч. автосубтитры YouTube), json whisper
    python3 cuts.py transcript.json --floor 0.35 --json
    python3 cuts.py transcript.json --edl cut.edl --clip raw.mp4    # CMX3600 для монтажки, fps из файла
    python3 cuts.py transcript.json --edl cut.edl --fps 25          # fps задан вручную
    python3 cuts.py transcript.json --ffmpeg raw.mp4                # команда для чернового реза

Находит три вещи:
  ПАУЗА    тишина длиннее порога (--floor, 0.45с); режется из середины, с обеих сторон остаётся
           вдох в полпорога. Тишина до первого слова режется так же, вдох остаётся перед словом
  ВОДА     реплика или слово, в котором только "э-э", "ну вот", "короче"
  ДУБЛЬ    фраза начата заново - вырезается первая попытка и пауза до второй, кроме вдоха в полпорога

В списке - каждая находка отдельно. Находки пересекаются и вкладываются друг в друга, поэтому в
итоге два числа: сколько находок и сколько мест на таймлинии (слитых областей реза). Остаток между
двумя резами короче 0.3с не оставляется отдельным куском, а уходит в рез. В --json: "cuts" - находки,
"regions" - слитые области, "keep" - остающиеся куски [начало, конец] в секундах исходника,
"out" - длина результата.

FPS ДЛЯ EDL: --fps побеждает всегда; иначе читается ffprobe из файла --clip (или --ffmpeg), если
файл и ffprobe есть; иначе 25 с предупреждением. Откуда взят fps, печатается. Таймкоды EDL считаются
в целых кадрах, non-drop; для 29.97 и 23.976 счёт идёт по базе 30 и 24. EDL исходит из того, что
таймкод исходника начинается с 00:00:00:00.

Транскрипт кончается последним словом, поэтому всё, что в записи после него, в результат не попадает.

--at 47.7,1:03 пересчитывает моменты исходника на время после реза (для таймкодов Shorts и ссылок).

ТОЧНОСТЬ ЗАВИСИТ ОТ ТРАНСКРИПТА. С таймкодами по словам (whisper --word_timestamps True) паузы
видны и внутри фраз. С таймкодами по фразам видны только паузы между фразами, и инструмент об этом
скажет. В автосубтитрах YouTube концы слов оценены, а не измерены - это черновик.

Файл видео инструмент не трогает. Он печатает список, ты применяешь его в своей монтажке.
"""
import json, math, os, re, shlex, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import guard, usage, number, tokens, parse_args, load_transcript, die, remap, parse_ts, fmt_ts

_F = (r"um+|uh+|er+|ah+|hm+|э+м*|а+м+|м+|ну|вот|так|значит|короче|типа|ладно|окей|ок|ok|okay|so|right|yeah|like|"
      r"anyway|basically|actually|you know|i mean|hold on|в общем|как бы|это самое|так сказать|скажем так|"
      r"слушайте|смотрите|сейчас|секунду")
FILLER_ONLY = re.compile(r"^[\s,.…!?-]*((" + _F + r")[\s,.…!?-]*)+$", re.I)
FILLER_WORD = re.compile(r"^[\s,.…-]*(um+|uh+|er+|ah+|hm+|э+м*|а+м+|м{2,})[\s,.…-]*$", re.I)
MIN_KEEP = 0.3                                       # остаток короче - не кусок, а мусор между резами

def find_cuts(tr, floor):
    cuts = []
    units = tr.words or tr.segs                      # паузы ищем на самом мелком доступном уровне
    first = min(units[0][0], tr.segs[0][0])
    if first > floor:
        cuts.append({"kind": "ПАУЗА", "start": 0.0, "end": first - floor / 2, "why": f"тишина в начале {first:.2f}с"})
    for i in range(1, len(units)):
        gap = units[i][0] - units[i - 1][1]
        if gap > floor:
            keep = floor / 2
            cuts.append({"kind": "ПАУЗА", "start": units[i - 1][1] + keep, "end": units[i][0] - keep,
                         "why": f"тишина {gap:.2f}с"})
    for s, e, t in tr.words:
        if FILLER_WORD.match(t): cuts.append({"kind": "ВОДА", "start": s, "end": e, "why": t.strip()})
    speech = []                                      # индексы фраз, в которых есть речь
    for i, (s, e, t) in enumerate(tr.segs):
        if FILLER_ONLY.match(t):
            cuts.append({"kind": "ВОДА", "start": s, "end": e, "why": t.strip()[:48]}); continue
        if speech:
            ps, pe, pt = tr.segs[speech[-1]]
            a, b = tokens(pt)[:5], tokens(t)[:5]
            k = 0
            while k < min(len(a), len(b)) and a[k] == b[k]: k += 1
            # дубль: совпали первые 3+ слова, и попытки идут подряд (до 20 секунд между ними)
            if k >= 3 and s - pe < 20:
                cuts.append({"kind": "ДУБЛЬ", "start": ps, "end": max(ps, s - floor / 2), "why": f'повтор начала "{" ".join(a[:k])}"'})
        speech.append(i)
    cuts = [c for c in cuts if c["end"] - c["start"] >= 0.08]     # рез короче пары кадров не нужен
    cuts.sort(key=lambda c: (c["start"], c["end"]))
    return cuts

def regions(cuts, dur):
    """Слитые области реза. Остаток короче MIN_KEEP между резами (и у краёв записи) уходит в рез."""
    out = []
    for c in cuts:
        a, b = max(0.0, c["start"]), min(dur, c["end"])
        if b <= a: continue
        if out and a - out[-1][1] < MIN_KEEP: out[-1][1] = max(out[-1][1], b)
        else: out.append([a, b])
    if out and out[0][0] < MIN_KEEP: out[0][0] = 0.0
    if out and dur - out[-1][1] < MIN_KEEP: out[-1][1] = dur
    return out

def keeps(reg, dur):
    out, t = [], 0.0
    for a, b in reg:
        if a > t: out.append((t, a))
        t = b
    if dur > t: out.append((t, dur))
    return out

def probe_fps(path):
    """Частота кадров видеопотока через ffprobe или None, если нет файла, ffprobe или видео в файле."""
    if not path or not os.path.isfile(path) or not shutil.which("ffprobe"): return None
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                            "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=20)
        n, _, d = p.stdout.strip().splitlines()[0].partition("/")
        v = float(n) / float(d or 1)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, ZeroDivisionError): return None
    return v if v >= 1 else None

def tc(f, base):
    return f"{f // (base * 3600):02d}:{f // (base * 60) % 60:02d}:{f // base % 60:02d}:{f % base:02d}"

def write_edl(path, keep, fps, clip):
    """Возвращает число событий. Всё в целых кадрах: границы исходника округляются один раз, позиция
    записи копит кадры, а не секунды - иначе длина события на двух сторонах расходится на кадр."""
    lines = [f"TITLE: {os.path.splitext(os.path.basename(path))[0]}", "FCM: NON-DROP FRAME", ""]
    base, rec, n = int(math.ceil(fps - 1e-6)), 0, 0   # 29.97 -> счёт по 30, 23.976 -> по 24
    for a, b in keep:
        fa, fb = int(round(a * fps)), int(round(b * fps))
        if fb <= fa: continue
        n += 1
        lines.append(f"{n:03d}  AX       AA/V  C        {tc(fa, base)} {tc(fb, base)} {tc(rec, base)} {tc(rec + fb - fa, base)}")
        lines.append(f"* FROM CLIP NAME: {clip}")
        rec += fb - fa
    with open(path, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    return n

def ffmpeg_cmd(src, keep):
    sel = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
    base, ext = os.path.splitext(src)
    return (f"ffmpeg -i {shlex.quote(src)} -vf \"select='{sel}',setpts=N/FRAME_RATE/TB\" "
            f"-af \"aselect='{sel}',asetpts=N/SR/TB\" {shlex.quote(base + '.cut' + (ext or '.mp4'))}")

def main():
    pos, opt = parse_args(sys.argv[1:], flags=("--json",),
                          options=("--floor", "--edl", "--fps", "--clip", "--ffmpeg", "--at"))
    if not pos: usage(__doc__)
    tr = load_transcript(pos[0])
    floor, dur = number(opt, "--floor", 0.45, 0.05), tr.duration
    cuts = find_cuts(tr, floor)
    reg = regions(cuts, dur)
    keep = keeps(reg, dur)
    removed = sum(b - a for a, b in reg)              # по слитым областям: пересечения считаются один раз
    out = sum(b - a for a, b in keep)
    level = ("слова, концы оценены" if tr.approx else "слова") if tr.words else "фразы"
    if "--at" in opt:                                 # пересчёт моментов исходника на время после реза
        rows = []
        for x in opt["--at"].split(","):
            try: t = parse_ts(x)
            except ValueError: die(f"--at: не понял время '{x.strip()}' - нужны секунды или мм:сс через запятую")
            inside = not any(a <= t <= b for a, b in keep)
            rows.append({"source": round(t, 2), "cut": round(remap(t, keep), 2), "removed": inside})
        if "--json" in opt: print(json.dumps(rows, ensure_ascii=False, indent=1)); return
        print("\n  время в исходнике -> время после реза")
        for r in rows:
            print(f"    {fmt_ts(r['source']):>7} ({r['source']:.1f}с) -> {fmt_ts(r['cut']):>7} ({r['cut']:.1f}с)"
                  + ("   этот момент вырезан - показано начало следующего куска" if r["removed"] else ""))
        print(); return
    res = {"source": pos[0], "level": level, "duration": round(dur, 3),
           "cuts": [dict(c, start=round(c["start"], 3), end=round(c["end"], 3)) for c in cuts],
           "regions": [[round(a, 3), round(b, 3)] for a, b in reg],
           "keep": [[round(a, 3), round(b, 3)] for a, b in keep],
           "removed": round(removed, 3), "out": round(out, 3)}
    if "--edl" in opt:
        src = opt.get("--clip") or opt.get("--ffmpeg")
        fps, fps_src = number(opt, "--fps", 25, 1), "задан"
        if "--fps" not in opt:
            found = probe_fps(src)
            fps, fps_src = (found, "прочитан из файла") if found else (25.0, "ПО УМОЛЧАНИЮ, проверь по исходнику, иначе резы съедут")
        events = write_edl(opt["--edl"], keep, fps, os.path.basename(src) if src else "source")
        res["edl"] = {"path": opt["--edl"], "events": events, "fps": round(fps, 3), "fps_source": fps_src}
    if "--json" in opt:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    print(f"\n  {pos[0]}   {dur:.2f}с, точность таймкодов: {level}, порог паузы {floor}с\n")
    for c in cuts:
        print(f"    {c['kind']:<6} {c['start']:8.2f} -> {c['end']:8.2f}   {c['end'] - c['start']:5.2f}с   {c['why']}")
    if not cuts: print("    резать нечего")
    print(f"\n  находок: {len(cuts)}, мест на таймлинии: {len(reg)}, убрано {removed:.2f}с, останется {out:.2f}с "
          f"({removed / dur * 100 if dur else 0:.1f}% короче)")
    if not tr.words:
        print("  ! таймкоды только по фразам: паузы внутри фраз не видны. Для точного реза сделай\n"
              "    транскрипт с таймкодами по словам (whisper --word_timestamps True --output_format json)")
    if "--edl" in opt:
        print(f"  EDL записан: {opt['--edl']} ({events} кусков)\n  fps {round(fps, 3):g} - {fps_src}")
    if "--ffmpeg" in opt: print(f"\n  черновой рез (перекодирует видео):\n  {ffmpeg_cmd(opt['--ffmpeg'], keep)}")
    print()

if __name__ == "__main__":
    guard(main)
