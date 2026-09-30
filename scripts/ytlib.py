#!/usr/bin/env python3
"""ytlib.py - общий код для инструментов yt-studio: разбор транскриптов, токены RU/EN,
voice.md, аргументы командной строки. Только стандартная библиотека.
"""
import json, os, re, sys

# Консоль Windows по умолчанию не в UTF-8: без этого кириллица в выводе роняет скрипт.
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError): pass

# Личные данные автора (voice.md, журнал) живут вне папки скилла, чтобы переживать обновления.
HOME_DIR = os.environ.get("YT_STUDIO_HOME") or os.path.expanduser("~/.claude/yt-studio")
VOICE_PATH = os.path.join(HOME_DIR, "voice.md")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

STOP = set("""
the a an of for to in on and or is are was were be been with this that it as at by from you your i my
we our they them he she but so if then than there here what which who how when where why not no yes
do does did just really very like about into over out up down can could will would should have has
had get got make made go going went one two
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее её мне
было вот от меня еще ещё нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него
до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы
тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому
этого какой совсем ним здесь этом один почти мой тем чтобы нее неё сейчас были куда зачем всех
никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего них
какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой
им более всегда конечно всю между это эта очень просто тебе свой свои наш ваш твой мои который
которые которая будут есть нужно поэтому также типа короче
""".split())

VAGUE = set("""
amazing incredible insane crazy huge massive ultimate best powerful secret revolutionary
mindblowing epic perfect unbelievable shocking
невероятный невероятно невероятная потрясающий потрясающе шок шокирующий шокирующая безумный
безумно безумие лучший лучшая лучшее лучшие огромный огромная секрет секретный секреты мощный
мощная идеальный идеальная идеально революционный жесть нереальный нереально уникальный
уникальная крутой круто бомба топ топовый имба
""".split())

# Числа словами, включая частые косвенные формы ("из десяти", "тридцати секунд"). "одно" здесь нет
# намеренно: "одно и то же", "одно дело" - не числа. Порядковые ("на второй неделе") ищет hook.py.
NUM_WORDS = ("один одна два две три четыре пять шесть семь восемь девять десять одиннадцать двенадцать "
             "пятнадцать двадцать тридцать сорок пятьдесят сто двести триста полтора "
             "двух трех четырех пяти шести семи восьми девяти десяти пятнадцати двадцати тридцати сорока ста "
             "тысяча тысяч тысячи миллион миллиона миллионов половина вдвое втрое "
             "one two three four five six seven eight nine ten eleven twelve fifteen twenty thirty forty fifty "
             "hundred thousand million half twice").split()

CLICHE = [r"всем привет", r"привет,? друзья", r"в этом (видео|ролике)", r"сегодня (я|мы) (расскажу|поговорим|разберем|разберём)",
          r"не забудь(те)? подписаться", r"ставь(те)? лайк", r"добро пожаловать на (мой )?канал", r"меня зовут",
          r"\bhey guys\b", r"\bwelcome back\b", r"\bin this video\b", r"\bbefore we (get )?start", r"\bmy name is\b",
          r"\bdon'?t forget to subscribe\b", r"\bwhat'?s up\b"]

def tokens(text):
    return re.findall(r"[a-zа-яё0-9']+", text.lower().replace("ё", "е"))

def stem(w):
    """Грубая основа слова: хватает, чтобы 'ошибка' и 'ошибки' считались одним словом."""
    if re.search(r"[а-я]", w):
        return w[:-2] if len(w) >= 6 else w[:-1] if len(w) >= 4 else w
    return w[:-1] if len(w) > 3 and w.endswith("s") else w

def same_root(a, b):
    """Похоже ли на одно слово в разных формах: 'ошибка'/'ошибки', 'клик'/'кликнут'. Эвристика по
    общему началу; приставочные пары ('листают'/'пролистывают') она не ловит."""
    if a == b: return True
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]: n += 1
    short = min(len(a), len(b))
    return n >= 5 or (n >= 4 and n >= 0.6 * short) or (short <= 4 and n == short and n >= 3)

def remap(t, keep):
    """Время исходника -> время после реза. keep - остающиеся куски [(начало, конец), ...]."""
    out = 0.0
    for a, b in keep:
        if t <= a: return out
        if t < b: return out + (t - a)
        out += b - a
    return out

def content_words(text, min_len=3):
    return [w for w in tokens(text) if w not in STOP and len(w) >= min_len]

# ---------------------------------------------------------------- аргументы

def parse_args(argv, flags=(), options=()):
    """Возвращает (позиционные, {опции}). flags - без значения, options - со значением.
    В отличие от фильтра "всё, что похоже на число, не файл" - имя файла '2024' тут выживает."""
    if "--help" in argv or "-h" in argv:                 # привычка сильнее документации
        usage(sys.modules["__main__"].__doc__ or "")
    pos, opt, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a in flags: opt[a] = True
        elif a in options:
            if i + 1 >= len(argv): die(f"после {a} нужно значение")
            opt[a] = argv[i + 1]; i += 1
        elif a.startswith("--"): die(f"неизвестный параметр {a}")
        else: pos.append(a)
        i += 1
    return pos, opt

def die(msg, code=1):
    print(msg, file=sys.stderr); sys.exit(code)

def usage(doc):
    """Запуск без аргументов - это вопрос "как пользоваться", а не ошибка: справка и код 0."""
    print(doc.strip()); sys.exit(0)

def number(opt, name, default, lo=None):
    """Числовой параметр с понятной ошибкой вместо трейсбека."""
    if name not in opt: return default
    try: v = float(str(opt[name]).replace(",", "."))
    except ValueError: die(f"{name}: нужно число, а получено '{opt[name]}'")
    if lo is not None and v < lo: die(f"{name}: не меньше {lo:g}")
    return v

_MULT = [(r"(млрд|billion|b)", 1e9), (r"(млн|миллион\w*|million|m|м)", 1e6), (r"(тыс|тысяч\w*|thousand|k|к)", 1e3)]

def human_number(text):
    """Число так, как его пишут люди: '8400', '8 400', '8,4 тыс', '1.2M', '310 тыс.', '6,2%'.
    Точка или запятая перед ровно тремя цифрами без множителя - разделитель тысяч ('8.400' = 8400).
    Возвращает float или None, если это не число."""
    t = str(text).strip().lower().replace("\u00a0", " ").rstrip("%").strip()
    mult = 1.0
    for pat, m in _MULT:
        mm = re.search(r"\s*" + pat + r"\.?$", t)
        if mm and re.match(r"^[\d\s.,]+$", t[:mm.start()]): t, mult = t[:mm.start()], m; break
    t = t.replace(" ", "")
    if not re.match(r"^\d+([.,]\d+)*$", t): return None
    if mult == 1.0 and re.match(r"^\d{1,3}([.,]\d{3})+$", t): return float(re.sub(r"[.,]", "", t))
    if t.count(",") + t.count(".") > 1: return None
    return float(t.replace(",", ".")) * mult

def duration(opt, name="--duration"):
    """Длина видео: секунды (600) или мм:сс / ч:мм:сс (10:00)."""
    if name not in opt: return None
    try: v = parse_ts(opt[name])
    except ValueError: die(f"{name}: нужны секунды или мм:сс, а получено '{opt[name]}'")
    if v <= 0: die(f"{name}: длина должна быть больше нуля")
    return v

def guard(main):
    """Обёртка точки входа: любая непредвиденная ошибка - одна понятная строка, а не трейсбек."""
    try: main()
    except KeyboardInterrupt: die("прервано", 130)
    except BrokenPipeError: sys.exit(0)
    except Exception as ex:                                  # noqa: BLE001
        die(f"внутренняя ошибка ({type(ex).__name__}: {ex}). Проверь входной файл; если он в порядке - "
            f"это баг инструмента, запусти doctor.py и сообщи о нём.", 70)

def read_text(path):
    """Текст файла в любой из частых кодировок: UTF-8 (с BOM и без), UTF-16, Windows-1251."""
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"): return raw.decode("utf-16", errors="replace")
    for enc in ("utf-8-sig", "cp1251"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    return raw.decode("utf-8", errors="replace")

# ---------------------------------------------------------------- транскрипты

def parse_ts(s):
    """'1:02:03,500', '02:03.5', '75' -> секунды. Дробная часть после запятой в три и более знака -
    это миллисекунды, как в SRT: кривое '23,1000' читается как 24.0, а не как 23.1."""
    p = s.strip().split(":")
    m = re.match(r"^(\d+)[.,](\d+)$", p[-1].strip())
    if m:
        whole, frac = m.groups()
        sec = int(whole) + (int(frac) / 1000.0 if len(frac) >= 3 else float("0." + frac))
    else:
        sec = float(p[-1])
    head = [float(x) for x in p[:-1]]
    while len(head) < 2: head.insert(0, 0.0)
    if len(head) > 2: raise ValueError(s)
    return head[0] * 3600 + head[1] * 60 + sec

def fmt_ts(t, hours=False):
    t = int(t + 1e-6); h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if (h or hours) else f"{m}:{s:02d}"

_TAG_TS = re.compile(r"<(\d\d:\d\d:\d\d[.,]\d+)>")
_TIMING = re.compile(r"\s*(\d[\d:.,]+)\s*-->\s*(\d[\d:.,]+)")

class Transcript:
    """segs - фразы [(start, end, text)], words - слова [(start, end, word)] или [].
    approx=True значит, что концы слов оценены (автосубтитры YouTube), а не измерены."""
    def __init__(self, segs, words=None, approx=False):
        self.segs, self.words, self.approx = segs, words or [], approx
    @property
    def duration(self):
        return max([s[1] for s in self.segs] + [w[1] for w in self.words] + [0.0])
    def text_between(self, a, b):
        return " ".join(s[2] for s in self.segs if s[1] >= a and s[0] <= b)

def _phrases(words, gap=0.6, max_words=16):
    segs, cur = [], []
    for w in words:
        if cur and (w[0] - cur[-1][1] > gap or len(cur) >= max_words or re.search(r"[.!?]$", cur[-1][2])):
            segs.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur))); cur = []
        cur.append(w)
    if cur: segs.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
    return segs

def _load_json(raw):
    d = json.loads(raw)
    segs_in = d.get("segments", []) if isinstance(d, dict) else d
    if not isinstance(segs_in, list): segs_in = []
    segs, words = [], []
    # verbose_json от OpenAI API кладёт слова списком верхнего уровня, а не внутрь сегментов
    top = d.get("words") if isinstance(d, dict) else None
    for w in top if isinstance(top, list) else []:
        word = (w.get("word") or w.get("text") or "").strip()
        if word and w.get("start") is not None and w.get("end") is not None:
            words.append((float(w["start"]), float(w["end"]), word))
    if not segs_in and words: return Transcript(_phrases(words), words)
    for s in segs_in:
        text = (s.get("text") or "").strip()
        if text: segs.append((float(s["start"]), float(s["end"]), text))
        for w in ([] if top else s.get("words") or []):
            word = (w.get("word") or w.get("text") or "").strip()
            if word and w.get("start") is not None and w.get("end") is not None:
                words.append((float(w["start"]), float(w["end"]), word))
    return Transcript(segs, words)

def _load_cues(raw):
    cues, cur = [], None
    for line in raw.splitlines():
        m = _TIMING.match(line)
        if m:
            cur = [parse_ts(m.group(1)), parse_ts(m.group(2)), []]; cues.append(cur)
        elif cur is not None and line.strip() and not line.strip().isdigit():
            cur[2].append(line.strip())
        elif not line.strip():
            cur = None if cur is not None and cur[2] else cur
    # Автосубтитры YouTube: слова размечены тегами <00:00:01.234> внутри строки
    if any(_TAG_TS.search(l) for c in cues for l in c[2]):
        starts = []
        for s, e, lines in cues:
            for l in lines:
                if not _TAG_TS.search(l): continue          # строка-повтор предыдущего кадра
                parts = _TAG_TS.split(l)                    # [текст, ts, текст, ts, текст...]
                t = s
                for k, part in enumerate(parts):
                    if k % 2: t = parse_ts(part); continue
                    w = re.sub(r"<[^>]+>", "", part).strip()
                    if w: starts.append((t, w))
        words = []
        for k, (t, w) in enumerate(starts):
            nxt = starts[k + 1][0] if k + 1 < len(starts) else t + 0.6
            words.append((t, min(nxt, t + 0.25 + 0.07 * len(w)), w))
        return Transcript(_phrases(words), words, approx=True)
    # Обычные srt/vtt. "Катящиеся" субтитры повторяют прошлую строку - убираем повторы.
    segs, prev = [], set()
    for s, e, lines in cues:
        clean = [re.sub(r"<[^>]+>", "", l).strip() for l in lines]
        fresh = [l for l in clean if l and l not in prev]
        prev = set(clean)
        if fresh and e > s: segs.append((s, e, " ".join(fresh)))
    return Transcript(segs)

def load_transcript(path):
    if not os.path.isfile(path): die(f"нет файла: {path}")
    raw = read_text(path)
    if not raw.strip(): die(f"файл пустой: {path}")
    try:
        tr = _load_json(raw) if path.lower().endswith(".json") else _load_cues(raw)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as ex:
        die(f"не смог разобрать {path}: {ex}")
    if not tr.segs: die(f"в {path} не нашлось реплик - это srt, vtt или json от whisper?")
    return tr

# ---------------------------------------------------------------- voice.md

def banned_words(path=None):
    """Слова из раздела 'Слова, которые я не использую' в voice.md. Нет файла - пустой список."""
    path = path or VOICE_PATH
    if not os.path.exists(path): return []
    out, inside = [], False
    text = re.sub(r"<!--.*?-->", "", read_text(path), flags=re.S)      # подсказки шаблона - не слова
    for line in text.splitlines():
        if line.startswith("#"):
            inside = bool(re.search(r"не использую|never use", line, re.I)); continue
        if not inside or line.lstrip().startswith(("<!--", ">")): continue
        quoted = re.findall(r"[\"«“]([^\"»”]+)[\"»”]", line)
        items = quoted or [x for x in re.split(r"[,;]", re.sub(r"^\s*[-*]\s*", "", line))]
        out += [x.strip().lower() for x in items if x.strip()]
    return out

def find_banned(text, banned):
    """Записи из banned, которые встретились в тексте, каждая один раз и в том виде, как в списке.
    Одно слово ловится и в другой форме (мотивация -> мотивации, мотивацией; hack -> hacks), но не
    однокоренные слова (мотив, мотивировать). Фраза из нескольких слов ищется как есть."""
    norm = lambda s: s.lower().replace("ё", "е")
    low = norm(text)
    words = set(re.findall(r"[a-zа-я0-9']+", low))
    # словарное окончание -> окончания других форм того же слова. Сравнение по общему началу
    # ("мотив" внутри "мотивация") ловило бы чужие слова, поэтому дописать можно только окончание.
    adj = "ый ий ой ая яя ое ее ого его ому ему ым им ом ем ую юю ые ие ых их ыми ими ей о"
    rows = [("ия", "ия ии ию ией ий иям иями иях"), ("ие", "ие ия ию ием ии ий иям иями иях " + adj),
            ("ый", adj), ("ий", adj), ("ой", adj), ("ая", adj), ("яя", adj), ("ое", adj), ("ее", adj), ("ые", adj),
            ("ка", "ок ек"), ("й", "й я ю ем е и ев ей ям ями ях"), ("а", "а ы и е у ой ою ам ами ах +"),
            ("я", "я и е ю ей ь ям ями ях"), ("о", "о а у ом е ам ами ах"), ("е", "е я ю ем ей ям ями ях"),
            ("ь", "ь и ью я ю ем ей ям ями ях"), ("ы", "ы ов ам ами ах а у ом е +"),
            ("и", "и ов ев ей ам ям ами ями ах ях а я у ю ом ем е +"), ("", "а у ом е ы и ов ев ем ей ам ами ах")]
    def forms(b):
        out = {b}
        if re.match(r"^[a-z']+$", b):
            if len(b) > 2:
                out |= {b + x for x in ("s", "es", "'s", "d", "ed", "ing", b[-1] + "ed", b[-1] + "ing")}
                if b[-1] == "e": out |= {b[:-1] + "ing"}
                if b[-1] == "y": out |= {b[:-1] + "ies", b[:-1] + "ied"}
            return out
        for end, tails in rows:
            base = b[:len(b) - len(end)]
            if not b.endswith(end) or len(base) < 3 or (not end and b[-1] in "аеиоуыэюяйь"): continue
            # "+" - форма без окончания (тысяч, дисциплин); у коротких слов она слишком часто
            # совпадает с чужим словом (тема -> "тем более")
            out |= {base + x for x in tails.split() if x != "+"} | ({base} if "+" in tails and len(base) >= 4 else set())
        return out
    found = []
    for b in banned:
        key = norm(b).strip()
        if not key or b in found: continue
        if re.match(r"^[a-zа-я']+$", key): hit = bool(forms(key) & words)
        else: hit = bool(re.search(r"(?<![a-zа-я])" + re.escape(key), low))
        if hit: found.append(b)
    return found

def load_formulas():
    return json.load(open(os.path.join(DATA_DIR, "hooks.json"), encoding="utf-8"))["hooks"]

def classify(text, formulas=None):
    # Побеждает формула с большим числом совпавших шаблонов; при равенстве - та, чей шаблон
    # сработал раньше по тексту: форму хука задаёт его начало.
    best, hits, pos = None, 0, 0
    for f in formulas or load_formulas():
        found = [m.start() for m in (re.search(p, text, re.I) for p in f["match"]) if m]
        if found and (len(found), -min(found)) > (hits, -pos): best, hits, pos = f, len(found), min(found)
    return (best["name"] if best else "не определена"), hits
