#!/usr/bin/env python3
"""Проверка cuts.py: кадры в EDL, слитые области, вдох у дубля, тишина в начале, источник fps.
Запуск: python3 tests/test_cuts.py"""
import json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL, D = os.path.join(ROOT, "scripts", "cuts.py"), os.path.join(ROOT, "tests", "data")
fails = []

def raw(*args, env=None):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=dict(os.environ, **(env or {})))

def run(*args, env=None):
    p = raw(*args, env=env)
    if p.returncode != 0: fails.append(f"cuts.py {args}: код {p.returncode}\n{p.stderr}")
    return p.stdout

def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

def skip(name, why):
    print(f"  skip {name} ({why})")

d = lambda f: os.path.join(D, f)

def events(path, base):
    """События EDL как четвёрки номеров кадров: исходник от/до, запись от/до."""
    out = []
    for line in open(path, encoding="utf-8"):
        tcs = re.findall(r"\b(\d\d):(\d\d):(\d\d):(\d\d)\b", line)
        if len(tcs) == 4:
            assert all(int(f) < base for _, _, _, f in tcs), line
            out.append([((int(h) * 60 + int(m)) * 60 + int(s)) * base + int(f) for h, m, s, f in tcs])
    return out

def srt(path, cues):
    ts = lambda t: "%02d:%02d:%06.3f" % (t // 3600, t % 3600 // 60, t % 60)
    with open(path, "w", encoding="utf-8") as f:
        for n, (a, b, text) in enumerate(cues, 1):
            f.write(f"{n}\n{ts(a).replace('.', ',')} --> {ts(b).replace('.', ',')}\n{text}\n\n")

talk = json.loads(run(d("talk.srt"), "--json"))
text = run(d("talk.srt"))

with tempfile.TemporaryDirectory() as tmp:
    t = lambda name: os.path.join(tmp, name)

    # 1. кадры: длина события в исходнике и в записи совпадает, запись идёт встык
    for fps, base in (("25", 25), ("29.97", 30), ("23.976", 24)):
        run(d("talk.srt"), "--edl", t("a.edl"), "--fps", fps)
        ev = events(t("a.edl"), base)
        same = all(so - si == ro - ri and so > si for si, so, ri, ro in ev)
        butt = all(ev[i][2] == (ev[i - 1][3] if i else 0) for i in range(len(ev)))
        src = [[int(round(a * float(fps))), int(round(b * float(fps)))] for a, b in talk["keep"]]
        check(f"EDL {fps} fps: длина в кадрах в исходнике и в записи одна, куски встык",
              len(ev) == len(talk["keep"]) and same and butt and [e[:2] for e in ev] == src)
    run(d("talk.srt"), "--edl", t("a.edl"), "--fps", "29.97")
    check("EDL 29.97 fps: non-drop, номер кадра не доходит до 30", "FCM: NON-DROP FRAME" in open(t("a.edl")).read())

    # 2. огрызков нет, итоги считаются от списка кусков
    for name in ("talk.srt", "words.json", "auto.vtt"):
        r = json.loads(run(d(name), "--json"))
        kept = sum(b - a for a, b in r["keep"])
        check(f"{name}: нет куска короче 0.3с, removed/out сходятся с keep",
              all(b - a >= 0.3 - 1e-6 for a, b in r["keep"]) and abs(r["out"] - kept) < 0.01
              and abs(r["duration"] - r["removed"] - kept) < 0.01
              and abs(r["removed"] - sum(b - a for a, b in r["regions"])) < 0.01)
    check("talk.srt: 0.2с между ВОДА и ДУБЛЬ ушли в рез", not any(abs(a - 31.4) < 0.01 for a, b in talk["keep"])
          and any(a <= 30.4 + 1e-6 and b >= 35.6 - 1e-6 for a, b in talk["regions"]))

    # 3. находки и места на таймлинии
    check("talk.srt: 8 находок, 5 мест на таймлинии", len(talk["cuts"]) == 8 and len(talk["regions"]) == 5
          and "находок: 8, мест на таймлинии: 5" in text)
    check("json: keep - пары [начало, конец], области и куски покрывают всю длину",
          all(len(k) == 2 and k[0] < k[1] for k in talk["keep"])
          and sorted(talk["keep"] + talk["regions"])[0][0] == 0
          and all(x[1] == y[0] for x, y in zip(sorted(talk["keep"] + talk["regions"]), sorted(talk["keep"] + talk["regions"])[1:]))
          and sorted(talk["keep"] + talk["regions"])[-1][1] == talk["duration"])

    # 4. вдох у дубля и тишина в начале
    dub = [c for c in talk["cuts"] if c["kind"] == "ДУБЛЬ"]
    check("ДУБЛЬ кончается за полпорога до второй попытки", len(dub) == 1 and abs(dub[0]["end"] - (35.8 - 0.225)) < 0.002)
    r = json.loads(run(d("talk.srt"), "--floor", "1", "--json"))
    check("ДУБЛЬ: вдох следует за --floor", [c["end"] for c in r["cuts"] if c["kind"] == "ДУБЛЬ"] == [35.3])
    srt(t("dub.srt"), [(1.0, 2.0, "Раз два три четыре"), (2.1, 4.0, "Раз два три четыре пять шесть")])
    r = json.loads(run(t("dub.srt"), "--floor", "3", "--json"))
    check("ДУБЛЬ не кончается раньше своего начала", all(c["end"] >= c["start"] for c in r["cuts"]) and not
          [c for c in r["cuts"] if c["kind"] == "ДУБЛЬ"])
    srt(t("lead.srt"), [(3.0, 5.0, "Первая фраза после долгой тишины."), (5.2, 8.0, "Вторая фраза идёт сразу.")])
    r = json.loads(run(t("lead.srt"), "--json"))
    check("тишина в начале режется, перед первым словом остаётся полпорога",
          r["regions"] == [[0.0, 2.775]] and r["keep"] == [[2.775, 8.0]] and r["out"] == 5.225)
    check("короткая тишина в начале не режется", talk["keep"][0][0] == 0 and talk["cuts"][0]["start"] > 3)
    json.dump({"words": [{"word": "Раз", "start": 2.0, "end": 2.3}, {"word": "два", "start": 2.4, "end": 2.9}]},
              open(t("w.json"), "w"), ensure_ascii=False)
    r = json.loads(run(t("w.json"), "--json"))
    check("тишина в начале: таймкоды по словам", r["keep"] == [[1.775, 2.9]])

    # 5. откуда fps
    out = run(d("talk.srt"), "--edl", t("a.edl"), "--fps", "25")
    check("fps задан: так и сказано", "fps 25 - задан" in out)
    out = run(d("talk.srt"), "--edl", t("a.edl"))
    check("fps не задан и файла нет: громкое предупреждение", "fps 25 - ПО УМОЛЧАНИЮ, проверь по исходнику, иначе резы съедут" in out)
    out = run(d("talk.srt"), "--edl", t("a.edl"), "--clip", t("нет-такого.mp4"))
    check("--clip на несуществующий файл: fps по умолчанию, имя клипа в EDL",
          "ПО УМОЛЧАНИЮ" in out and "* FROM CLIP NAME: нет-такого.mp4" in open(t("a.edl"), encoding="utf-8").read())
    check("без --edl про fps ни слова", "fps" not in text)
    r = json.loads(run(d("talk.srt"), "--edl", t("a.edl"), "--json"))
    check("json: источник fps указан", r["edl"]["fps"] == 25 and "ПО УМОЛЧАНИЮ" in r["edl"]["fps_source"] and r["edl"]["events"] == len(r["keep"]))

    clip = t("clip 2997.mp4")
    made = bool(shutil.which("ffmpeg")) and subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=30000/1001", "-t", "2", "-pix_fmt", "yuv420p", "-y", clip],
        capture_output=True).returncode == 0 and os.path.isfile(clip)
    if made and shutil.which("ffprobe"):
        out = run(d("talk.srt"), "--edl", t("p.edl"), "--clip", clip)
        ev = events(t("p.edl"), 30)
        check("fps читается из файла --clip через ffprobe", "fps 29.97 - прочитан из файла" in out
              and ev and ev[0][1] == int(round(talk["keep"][0][1] * 30000 / 1001)) and all(so - si == ro - ri for si, so, ri, ro in ev))
        check("fps читается и из файла --ffmpeg", "fps 29.97 - прочитан из файла" in run(d("talk.srt"), "--edl", t("p.edl"), "--ffmpeg", clip))
        check("--fps побеждает файл", "fps 24 - задан" in run(d("talk.srt"), "--edl", t("p.edl"), "--clip", clip, "--fps", "24"))
        r = json.loads(run(d("talk.srt"), "--edl", t("p.edl"), "--clip", clip, "--json"))
        check("json: fps из файла", r["edl"]["fps"] == 29.97 and r["edl"]["fps_source"] == "прочитан из файла")
    else:
        skip("fps из файла через ffprobe", "нет ffmpeg или ffprobe")
    # без ffprobe в PATH файл есть, а прочитать нечем: не падаем, а предупреждаем
    open(t("fake.mp4"), "wb").write(b"\0" * 64)
    p = raw(d("talk.srt"), "--edl", t("n.edl"), "--clip", clip if made else t("fake.mp4"), env={"PATH": tmp})
    check("нет ffprobe: fps по умолчанию с предупреждением, без падения", p.returncode == 0 and "ПО УМОЛЧАНИЮ" in p.stdout)
    if shutil.which("ffprobe"):
        p = raw(d("talk.srt"), "--edl", t("n.edl"), "--clip", t("fake.mp4"))
        check("файл не видео: fps по умолчанию с предупреждением", p.returncode == 0 and "ПО УМОЛЧАНИЮ" in p.stdout)
    else:
        skip("файл не видео", "нет ffprobe")

# 6. инструкция
doc = open(os.path.join(ROOT, "references", "edit.md"), encoding="utf-8").read()
need = ["доля от длины всего транскрипта", "молчаливая демонстрация", "Clip Attributes", "--clip", "Media Pool", "File → Import",
        "Premiere Pro", "00:00:00:00", "может называться иначе", "длиннее 10 минут", "чини\nкопию", "chapters.py transcript.json --cuts cuts.json"]
check("edit.md: fps, импорт, оговорки, порог, копия, главы после реза", not [x for x in need if x not in doc] and "процент от длины речи" not in doc)
cmds = re.findall(r"^python3 .*$", doc, re.M)
check("edit.md: команды в виде python3 ${CLAUDE_SKILL_DIR}/scripts/...", cmds and all(c.startswith("python3 ${CLAUDE_SKILL_DIR}/scripts/") for c in cmds))
src = open(TOOL, encoding="utf-8").read()
check("флаги cuts.py из edit.md есть в инструменте", all(f in src for f in set(re.findall(r"cuts\.py[^\n`]*?(--[a-z-]+)", doc))))

print("\n" + ("ВСЁ ПРОШЛО" if not fails else f"ПРОВАЛОВ: {len(fails)}\n" + "\n".join(fails)))
sys.exit(1 if fails else 0)
