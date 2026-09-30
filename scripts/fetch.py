#!/usr/bin/env python3
"""fetch.py - достать входные данные через yt-dlp, не вспоминая его ключи.

    python3 fetch.py captions "https://youtu.be/ID" --lang ru          # субтитры видео -> .vtt
    python3 fetch.py channel "https://www.youtube.com/@канал"          # список видео канала -> .json

captions  скачивает субтитры (авторские, а если их нет - автоматические) без самого видео.
          Результат годится для cuts.py, chapters.py и retention.py --transcript.
channel   сохраняет открытый список видео и Shorts канала с просмотрами (последние --limit, по
          умолчанию 40). Результат годится для outliers.py.

Файлы кладутся в текущую папку или в --out. С --json печатает {"saved": [пути], "kind": "captions"|"channel"},
а сообщения yt-dlp уходят в stderr. Нужен установленный yt-dlp; если его нет, инструмент
скажет, как поставить. Читаются только открытые данные, без входа в аккаунт.
"""
import glob, json, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ytlib import guard, usage, number, parse_args, die

INSTALL = ("yt-dlp не установлен. Поставь одним из способов и повтори:\n"
           "  macOS:    brew install yt-dlp\n"
           "  Windows:  winget install yt-dlp\n"
           "  любой:    python3 -m pip install -U yt-dlp")

def ytdlp():
    exe = shutil.which("yt-dlp")
    if exe: return [exe]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        die(INSTALL, 3)

def run(cmd, capture=False, quiet=False):
    try:
        if capture: return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return subprocess.run(cmd, stdout=sys.stderr if quiet else None)   # с --json в stdout только json
    except OSError as ex:
        die(f"не смог запустить yt-dlp: {ex}", 3)

def check_url(url):
    if not re.match(r"https?://", url): die(f"нужна ссылка, начинающаяся с https://, а получено '{url}'")

def captions(exe, url, out, lang, as_json):
    before = set(glob.glob(os.path.join(out, "*.vtt")))
    p = run(exe + ["--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", f"{lang}.*,{lang}",
                       "--sub-format", "vtt", "--no-playlist", "-o", os.path.join(out, "%(id)s.%(ext)s"), url], quiet=as_json)
    new = sorted(set(glob.glob(os.path.join(out, "*.vtt"))) - before)
    if p.returncode != 0 and not new: die("yt-dlp не смог получить субтитры (см. сообщение выше)", 2)
    if not new:
        die(f"у видео нет субтитров на языке '{lang}'. Попробуй другой --lang или сделай транскрипт\n"
            f"через whisper: whisper video.mp4 --word_timestamps True --output_format json", 2)
    if as_json: return done(new, "captions")
    print("\n  субтитры сохранены:")
    for f in new: print(f"    {f}")
    print("  дальше: cuts.py / chapters.py / retention.py --transcript с этим файлом\n")

def done(saved, kind):
    print(json.dumps({"saved": saved, "kind": kind}, ensure_ascii=False, indent=1))

def channel(exe, url, out, limit, as_json):
    base = re.sub(r"/(videos|shorts|streams|featured)/?$", "", url.rstrip("/"))
    slug = re.sub(r"[^\w-]+", "_", base.rsplit("/", 1)[-1].lstrip("@")).strip("_") or "channel"
    saved = []
    for tab in ("videos", "shorts"):
        p = run(exe + ["--flat-playlist", "-J", "--playlist-end", str(limit), f"{base}/{tab}"], capture=True)
        if p.returncode != 0 or not p.stdout.strip().startswith("{"):
            print(f"  вкладка {tab}: не получена" + (f" ({p.stderr.strip().splitlines()[-1][:120]})" if p.stderr.strip() else ""),
                  file=sys.stderr if as_json else sys.stdout)
            continue
        path = os.path.join(out, f"{slug}_{tab}.json")
        open(path, "w", encoding="utf-8").write(p.stdout)
        saved.append(path)
    if not saved: die("не удалось получить ни одной вкладки канала - проверь ссылку", 2)
    if as_json: return done(saved, "channel")
    print("\n  список канала сохранён:")
    for f in saved: print(f"    {f}")
    print("  дальше: outliers.py со всеми такими файлами по каналам ниши\n")

def main():
    argv = sys.argv[1:]
    if not argv: usage(__doc__)
    if len(argv) < 2 or argv[0] not in ("captions", "channel"): die(__doc__)
    pos, opt = parse_args(argv[1:], flags=("--json",), options=("--lang", "--out", "--limit"))
    if not pos: die(__doc__)
    check_url(pos[0])
    limit, as_json = int(number(opt, "--limit", 40, 5)), "--json" in opt
    exe = ytdlp()                                        # до создания папки: без yt-dlp не оставляем пустую --out
    out = opt.get("--out", ".")
    os.makedirs(out, exist_ok=True)
    if argv[0] == "captions": captions(exe, pos[0], out, opt.get("--lang", "ru"), as_json)
    else: channel(exe, pos[0], out, limit, as_json)

if __name__ == "__main__":
    guard(main)
