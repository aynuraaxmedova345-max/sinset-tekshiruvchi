#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UzWordNet talaba topshiriqlarini tekshiruvchi (1-bosqich: qoidaga asoslangan qism).

Ishlatish:
    python3 sinset_tekshiruvchi.py --lugat dictionary.sqlite --sozlar SOZLAR_PAPKASI \
        --chiqish HISOBOT_PAPKASI  talaba1.xlsx talaba2.xlsx ...

  --lugat    O'zbek tilining izohli lug'ati OCR bazasi (jasurshukurov/izohli_lugat, dictionary.sqlite)
  --sozlar   har bir talabaga berilgan 50 ta so'z fayllari (NN_FAMILIYA_ISM_..._QIZI.txt)
  --chiqish  hisobotlar yoziladigan papka

Har bir talaba fayli uchun <fayl>_TEKSHIRUV.xlsx hosil bo'ladi, oxirida UMUMIY_XULOSA.xlsx.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from rapidfuzz import fuzz

# --------------------------------------------------------------------------- #
#  Normalizatsiya
# --------------------------------------------------------------------------- #
APOS = "ʻʼ‘’`´'ʹʽʻʼ"
APOS_RE = re.compile("[" + re.escape(APOS) + "]")


def norm_word(w):
    """So'zni lug'at kaliti ko'rinishiga keltiradi (apostroflar birxillashtiriladi)."""
    w = str(w or "").replace("\xa0", " ").strip().lower()
    w = APOS_RE.sub("'", w)
    return re.sub(r"\s+", " ", w)


def letters(s):
    """Faqat harflar: OCR qator uzilishlari va tinish belgilaridan xoli solishtirish uchun."""
    s = str(s or "").lower()
    s = APOS_RE.sub("", s)
    s = s.replace("sh.k.", "shukabi").replace("sh. k.", "shukabi").replace("shu kabilar", "shukabi") \
         .replace("shu kabi", "shukabi")
    return re.sub(r"[^a-zа-яёқғҳў]", "", s)


def base_word(cell):
    """'chaqir_03' -> ('chaqir', 3);  'jamoa.n.03' -> ('jamoa', 3);  'atir' -> ('atir', None)"""
    s = str(cell or "").replace("\xa0", " ").strip()
    m = re.match(r"^(.*?)[\s_.\-]*(?:\.?[a-z]\.)?[_.\-\s]*\(?(\d{1,2})\)?$", s)
    if m and m.group(1).strip():
        return norm_word(m.group(1)), int(m.group(2))
    return norm_word(s), None


FILLER_RE = re.compile(r"\s*(degan\s+)?ma['ʻʼ‘’]?no(lar)?(i|ini|sini|larini)?\s+(bildiradi|anglatadi)\.?\s*$", re.I)


def clean_gloss(g):
    g = str(g or "").replace("\xa0", " ").strip()
    return FILLER_RE.sub("", g).strip()


def is_empty(v):
    return v is None or str(v).replace("\xa0", " ").strip() in ("", "-", "–", "—", "yo'q", "yoʻq", "yo‘q")


# --------------------------------------------------------------------------- #
#  Lug'at maqolasini ma'nolarga ajratish
# --------------------------------------------------------------------------- #
LABELS = {
    "rvsh.": "Ravish", "taql.s.": "Taqlid so'z", "taql. s.": "Taqlid so'z", "olm.": "Olmosh",
    "yukl.": "Yuklama", "bog'l.": "Bog'lovchi", "und.": "Undov", "und.s.": "Undov", "mod.s.": "Modal so'z",
    "mod. s.": "Modal so'z", "ko'm.": "Ko'makchi", "sft.": "Sifat", "son.": "Son",
}
ABBR = {"esk", "kt", "din", "mat", "s.t", "sh.k", "sh", "k", "ko'chma", "kam", "qo'll", "ayn", "q", "etn",
        "tar", "tib", "fiz", "kim", "biol", "bot", "zool", "geogr", "tlsh", "ad", "huq", "iqt", "siyos",
        "qar", "maxs", "poet", "shv", "dag'l", "hurm", "kest", "salb", "rvsh", "taql", "s", "olm", "yukl",
        "va", "b", "h.k", "mas", "t", "o", "f", "a", "r", "lot", "yun", "ingl", "nem", "fr", "ital"}

SENSE_START = r"(?=(?:(?:ko'chma|kam|maxs|ayn|[a-z'‘.\-]{1,9}\.)\s*){0,5}[A-ZА-ЯЁ\"«({\-.])"


def clean_def(text):
    text = text.replace("\r", "")
    # sahifa uzilishi shovqini:  \n\n\x0c\n29402 524\n\n \n\n
    text = re.sub(r"\s*\x0c\s*(?:[^\n]{0,25}\n)?\s*", " ", text)
    return text.strip()


def strip_etymology(text):
    """Bosh qismdagi (a. ... — tarjima) etimologik qavsni olib tashlaydi."""
    m = re.search(r"\)", text[:260])
    if m and re.search(r"[—–=]", text[:m.start()]):
        head = text[:m.start()]
        # 1-ma'no raqami qavsdan oldin kelib qolmagan bo'lsin
        if not re.search(r"\n\s*\n", head):
            return text[m.end():].lstrip(" :;.,")
    return text


def first_sentence(par):
    """Ma'no bo'lagining izoh (gloss) qismi: birinchi gap. Qisqartmalardagi nuqtalar hisobga olinadi."""
    flat = re.sub(r"\s+", " ", par).strip()
    for m in re.finditer(r"[.:!?]+", flat):
        end = m.end()
        prev = flat[:m.start()].split(" ")[-1].lower().strip("(,;")
        prev = APOS_RE.sub("'", prev)
        nxt = flat[end:end + 3]
        if prev in ABBR or len(prev) <= 1:
            continue
        if end >= len(flat) or re.match(r"\s+[A-ZА-ЯЁ\"«\-—(\[{.]", nxt) or re.match(r"\s*[-—]", nxt):
            core = re.sub(r"\([^)]*\)", " ", flat[:end])
            core = " ".join(t for t in core.split() if APOS_RE.sub("'", t.lower()).strip(".,;:") not in ABBR)
            if len(letters(core)) >= 6:
                return flat[:end].strip(), flat[end:].strip()
    return flat, ""


def parse_entry(raw):
    """Maqolani ma'nolarga ajratadi.
    Qaytaradi: dict(senses=[{n, gloss, examples, phrases:[...], text}], labels=set(), numbered=bool)
    """
    text = clean_def(raw)
    labels = set()
    low = APOS_RE.sub("'", text[:400].lower())
    for k, v in LABELS.items():
        if re.search(r"(?<![a-z'])" + re.escape(k), low):
            labels.add(v)

    # raqamli ma'no boshlanishlari (qator boshida)
    marks = []  # (pos_start, pos_text, n)
    expected = 2
    for m in re.finditer(r"(?:^|\n)[ \t]*(\d{1,2})[ \t]+" + SENSE_START, text):
        n = int(m.group(1))
        if n in (expected, expected + 1):
            marks.append((m.start(), m.end(), n))
            expected = n + 1
    senses = []
    if marks:
        head = text[:marks[0][0]]
        m1 = None
        for m in re.finditer(r"(?<![\dA-Za-z])1\s+" + SENSE_START, head):
            m1 = m
            break
        first_body = head[m1.end():] if m1 else strip_etymology(head)
        blocks = [(1, first_body)]
        for i, (s, e, n) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            blocks.append((n, text[e:end]))
    else:
        blocks = [(1, strip_etymology(text))]

    for n, body in blocks:
        pars = [p.strip() for p in re.split(r"\n\s*\n", body) if len(letters(p)) >= 4]
        if not pars:
            continue
        gloss, ex = first_sentence(pars[0])
        senses.append({"n": n, "gloss": gloss, "examples": ex,
                       "phrases": [re.sub(r"\s+", " ", p) for p in pars[1:]],
                       "text": re.sub(r"\s+", " ", body).strip()})
    return {"senses": senses, "labels": labels, "numbered": bool(marks),
            "missing_numbers": sorted(set(range(1, (senses[-1]["n"] if senses else 0) + 1))
                                      - {s["n"] for s in senses})}


class Lugat:
    def __init__(self, path):
        con = sqlite3.connect(path)
        self.idx = defaultdict(list)
        for latin, d in con.execute("select latin, latin_def from izohli"):
            if latin and d:
                self.idx[norm_word(latin)].append(d)
        con.close()
        self._cache = {}

    def has(self, w):
        return w in self.idx

    def entry(self, w):
        if w not in self._cache:
            if w not in self.idx:
                self._cache[w] = None
            else:
                parsed = [parse_entry(d) for d in self.idx[w]]
                # omonimlar (bir necha maqola) ketma-ket birlashtiriladi
                senses, labels, k = [], set(), 0
                for p in parsed:
                    labels |= p["labels"]
                    for s in p["senses"]:
                        k += 1
                        s = dict(s)
                        s["n"] = k if len(parsed) > 1 else s["n"]
                        senses.append(s)
                self._cache[w] = {"senses": senses, "labels": labels, "word": w,
                                  "missing_numbers": parsed[0]["missing_numbers"] if len(parsed) == 1 else []}
        return self._cache[w]


# --------------------------------------------------------------------------- #
#  Talaba faylini o'qish
# --------------------------------------------------------------------------- #
COLS = {
    "soz": ["so'z", "soz", "lemma", "synset id", "sinset id"],
    "sinonim": ["sinonim"],
    "izoh": ["izoh", "gloss"],
    "misol": ["misol"],
    "turkum": ["turkum", "pos"],
    "soha": ["soha"],
    "antonim": ["antonim"],
    "giperonim": ["giperonim"],
    "giponim": ["giponim"],
    "xolonim": ["xolonim", "holonim"],
    "meronim": ["meronim"],
    "manba": ["manba"],
}
REQUIRED = ["soz", "sinonim", "izoh", "misol", "turkum", "soha", "antonim", "giperonim", "giponim",
            "xolonim", "meronim"]
UZ = {"soz": "So‘z", "sinonim": "Sinonimlari", "izoh": "Izohi (gloss)", "misol": "Misol gap",
      "turkum": "Turkumi", "soha": "Sohasi", "antonim": "Antonimi", "giperonim": "Giperonimi",
      "giponim": "Giponimlari", "xolonim": "Xolonimi", "meronim": "Meronimi", "manba": "Manba"}


def read_submission(path):
    wb = load_workbook(path, data_only=True)
    best = None
    for ws in wb.worksheets:
        for r in range(1, min(ws.max_row, 15) + 1):
            hdr = {}
            for c in range(1, min(ws.max_column, 30) + 1):
                v = ws.cell(r, c).value
                if v is None:
                    continue
                key = norm_word(v)
                for name, alts in COLS.items():
                    if name not in hdr and any(key.startswith(a) for a in alts):
                        hdr[name] = c
            if len(hdr) >= 4 and (best is None or len(hdr) > len(best[2])):
                best = (ws, r, hdr)
    if best is None:
        raise ValueError("Jadval sarlavhasi topilmadi (So‘z / Izohi / Misol gap ustunlari yo‘q)")
    ws, hr, hdr = best
    rows = []
    for r in range(hr + 1, ws.max_row + 1):
        rec = {k: ws.cell(r, c).value for k, c in hdr.items()}
        if all(v is None or str(v).strip() == "" for v in rec.values()):
            continue
        rec["_row"] = r
        rows.append(rec)
    header_vals = [ws.cell(hr, c).value for c in range(1, ws.max_column + 1)]
    all_rows = [[ws.cell(r["_row"], c).value for c in range(1, ws.max_column + 1)] for r in rows]
    return {"sheet": ws.title, "header_row": hr, "hdr": hdr, "rows": rows,
            "header_vals": header_vals, "all_rows": all_rows}


# --------------------------------------------------------------------------- #
#  So'z ro'yxatlari va talabani aniqlash
# --------------------------------------------------------------------------- #
def name_key(s):
    s = norm_word(s).replace("'", "")
    s = re.sub(r"[^a-z]+", " ", s)
    return [t for t in s.split() if t not in ("qizi", "o'g'li", "ogli", "gr", "guruh", "wordnet", "klwordnet",
                                             "kl", "xlsx", "sinset", "uzwordnet")]


def load_wordlists(folder):
    out = {}
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith(".txt"):
            continue
        with open(os.path.join(folder, fn), encoding="utf-8") as f:
            words = [norm_word(x) for x in f.read().splitlines() if x.strip()]
        full = re.sub(r"^\d+_", "", fn[:-4]).replace("_", " ")
        out[full] = {"words": words, "file": fn, "key": name_key(full)}
    return out


def find_student(xlsx_name, wordlists):
    toks = name_key(os.path.splitext(os.path.basename(xlsx_name))[0])
    best, best_sc = None, 0
    for full, info in wordlists.items():
        fam, ism = info["key"][0], info["key"][1] if len(info["key"]) > 1 else ""
        sc_f = max([fuzz.ratio(fam, t) for t in toks] or [0])
        sc_i = max([fuzz.ratio(ism, t) for t in toks] or [0])
        sc = 0.6 * sc_f + 0.4 * sc_i
        if sc_f >= 85 and sc > best_sc:
            best, best_sc = full, sc
    return best, best_sc


# --------------------------------------------------------------------------- #
#  Tekshiruv
# --------------------------------------------------------------------------- #
XATO, OGOH, KORIB = "XATO", "OGOHLANTIRISH", "KO‘RIB CHIQISH"
POS_OK = {"ot": "Ot", "sifat": "Sifat", "fe'l": "Fe'l", "fel": "Fe'l", "ravish": "Ravish", "son": "Son",
          "olmosh": "Olmosh", "taqlid so'z": "Taqlid so'z", "taqlid": "Taqlid so'z", "undov": "Undov",
          "undov so'z": "Undov", "modal so'z": "Modal so'z", "modal": "Modal so'z", "ko'makchi": "Ko'makchi",
          "bog'lovchi": "Bog'lovchi", "yuklama": "Yuklama", "noun": "Ot", "verb": "Fe'l", "adj": "Sifat",
          "adv": "Ravish"}


def pscore(a, b):
    a, b = letters(a), letters(b)
    if len(a) < 6 or len(b) < 6:
        return 0.0
    return fuzz.partial_ratio(a, b)


def split_items(cell):
    if is_empty(cell):
        return []
    return [x.strip() for x in re.split(r"[;,/]", str(cell).replace("\xa0", " ")) if x.strip() and x.strip() != "-"]


def short(s, n=170):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def match_rows(rows, entry):
    """Har bir qatorni lug'at ma'nosiga bog'laydi. Qaytaradi: list of dict."""
    res = []
    for r in rows:
        g = clean_gloss(r.get("izoh"))
        info = {"sense": None, "g_score": 0, "kind": "yo'q", "ex_sense": None, "ex_score": 0,
                "ex_in_gloss_sense": 0}
        if entry and entry["senses"] and len(letters(g)) >= 6:
            bg = max(((pscore(g, s["gloss"]), s["n"]) for s in entry["senses"]), default=(0, None))
            be = max(((pscore(g, s["examples"]), s["n"]) for s in entry["senses"] if s["examples"]),
                     default=(0, None))
            bp = max(((pscore(g, p), s["n"]) for s in entry["senses"] for p in s["phrases"]), default=(0, None))
            # uzun izoh bir necha gapdan iborat bo'lsa, butun ma'no matni bilan ham solishtiriladi
            bt = max(((pscore(g, s["text"].split(" ", 0)[0] if False else s["gloss"] + " " + s["examples"]), s["n"])
                      for s in entry["senses"]), default=(0, None))
            if len(letters(g)) < 12:
                # juda qisqa izoh: faqat ma'no izohining o'zi bilan deyarli to'liq mos kelsa qabul qilinadi
                be, bp, bt = (0, None), (0, None), (0, None)
                bg = bg if bg[0] >= 90 else (0, None)
            if bg[0] >= 78 and bg[0] >= max(be[0], bp[0]) - 6:
                info.update(sense=bg[1], g_score=bg[0], kind="izoh")
            elif bp[0] >= 78 and bp[0] > be[0]:
                info.update(sense=bp[1], g_score=bp[0], kind="birikma")
            elif be[0] >= 80 and len(letters(g)) >= 20:
                info.update(sense=be[1], g_score=be[0], kind="misol")
            elif bt[0] >= 78 and len(letters(g)) >= 25:
                info.update(sense=bt[1], g_score=bt[0], kind="izoh")
            elif max(bg[0], bp[0]) >= 60:
                top = bg if bg[0] >= bp[0] else bp
                info.update(sense=top[1], g_score=top[0], kind="o'xshash")
            else:
                info.update(g_score=max(bg[0], bp[0], be[0]))
        ex = r.get("misol")
        if entry and entry["senses"] and len(letters(ex)) >= 10:
            be = max(((pscore(ex, s["text"]), s["n"]) for s in entry["senses"]), default=(0, None))
            info.update(ex_score=be[0], ex_sense=be[1] if be[0] >= 75 else None)
            if info["sense"] is not None:
                for s in entry["senses"]:
                    if s["n"] == info["sense"]:
                        info["ex_in_gloss_sense"] = pscore(ex, s["text"])
        res.append(info)
    return res


def check_submission(path, sub, assigned, lugat, student=None):
    """Qaytaradi: (issues, row_notes, word_table, stats)"""
    issues = []  # dict(row, soz, ustun, daraja, xato, lugatda, tavsiya)
    rows = sub["rows"]
    hdr = sub["hdr"]

    def add(row, soz, ustun, daraja, xato, lugatda="", tavsiya=""):
        issues.append({"row": row, "soz": soz, "ustun": ustun, "daraja": daraja, "xato": xato,
                       "lugatda": lugatda, "tavsiya": tavsiya})

    # --- 1. tuzilma -------------------------------------------------------- #
    for k in REQUIRED:
        if k not in hdr:
            add("", "", UZ[k], XATO, f"«{UZ[k]}» ustuni jadvalda yo‘q", "", "Namuna shablonidagi ustunlar to‘liq bo‘lsin")

    # --- 2. so'zlar bo'yicha guruhlash ------------------------------------- #
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        w, n = base_word(r.get("soz"))
        r["_w"], r["_n"] = w, n
        if not w:
            add(r["_row"], "", UZ["soz"], XATO, "So‘z ustuni bo‘sh")
            continue
        groups[w].append(i)

    assigned = list(assigned or [])
    aset = set(assigned)
    done = set(groups)
    missing = [w for w in assigned if w not in done]
    extra = [w for w in groups if aset and w not in aset]

    # berilmagan so'z -> ehtimoliy "o'rniga" so'z
    replaced = {}
    for w in extra:
        cand = max(missing, key=lambda m: fuzz.ratio(w, m), default=None)
        if cand and (fuzz.ratio(w, cand) >= 70 or (cand + "moq") == w or w.startswith(cand)):
            replaced[w] = cand
    for w in missing:
        ent = lugat.entry(w)
        nsen = len(ent["senses"]) if ent else 0
        used = [k for k, v in replaced.items() if v == w]
        add("", w, UZ["soz"], XATO,
            f"Berilgan «{w}» so‘zi ishlanmagan" + (f" (o‘rniga «{used[0]}» yozilgan)" if used else ""),
            f"Lug‘atda {nsen} ta ma’no: " + " | ".join(f"{s['n']}) {short(s['gloss'], 90)}" for s in (ent["senses"] if ent else [])),
            f"«{w}» uchun {nsen} ta sinset tuzilsin")
    for w in extra:
        for i in groups[w][:1]:
            add(rows[i]["_row"], w, UZ["soz"], XATO,
                f"«{w}» so‘zi talabaga berilgan 50 ta so‘z ro‘yxatida yo‘q"
                + (f" (ehtimol «{replaced[w]}» o‘rniga)" if w in replaced else ""), "",
                "Berilgan ro‘yxatdagi so‘z ishlansin")

    # --- 3. har bir so'z: lug'at bilan solishtirish ------------------------- #
    word_table = []
    row_notes = [dict(sense="", g="", e="", holat="", sin="") for _ in rows]
    row_entry, row_kind, row_sense, row_used = {}, {}, {}, {}
    seen_examples = defaultdict(list)

    for w, idxs in groups.items():
        grp = [rows[i] for i in idxs]
        ent = lugat.entry(w)
        used_entry = w
        m = match_rows(grp, ent)
        avg = sum(x["g_score"] for x in m) / len(m)
        # boshqa maqola ishlangan bo'lishi mumkin (masalan: chaqir -> chaqirmoq)
        alts = [a for a in (w + "moq", w[:-3] if w.endswith("moq") else None, w + "lik", w + "li") if a and lugat.has(a)]
        for a in alts:
            ma = match_rows(grp, lugat.entry(a))
            avga = sum(x["g_score"] for x in ma) / len(ma)
            if avga > avg + 15 and avga >= 70:
                orig = ent
                ent, m, avg, used_entry = lugat.entry(a), ma, avga, a
                add(grp[0]["_row"], w, UZ["soz"], OGOH,
                    f"Berilgan so‘z «{w}», lekin izohlar lug‘atdagi «{a}» maqolasidan olingan",
                    (f"«{w}»: " + " | ".join(short(s["gloss"], 90) for s in orig["senses"])) if orig else "",
                    f"Aynan «{w}» so‘zi ishlanishi kerakmi yoki «{a}» — o‘qituvchi aniqlashtirsin")
        if ent is None:
            add(grp[0]["_row"], w, UZ["soz"], KORIB, f"«{w}» so‘zi lug‘at bazasida topilmadi — qo‘lda tekshirilsin")
            word_table.append([w, "+" if w in aset else "–", used_entry, "", len(grp), "", "", "Lug‘atda topilmadi"])
            continue

        nsen = len(ent["senses"])
        covered = defaultdict(list)
        for r, x, i in zip(grp, m, idxs):
            soz = str(r.get("soz") or "").strip()
            note = row_notes[i]
            row_entry[i], row_kind[i], row_sense[i], row_used[i] = ent, x["kind"], x["sense"], used_entry
            note["g"] = round(x["g_score"])
            note["e"] = round(x["ex_score"])
            if x["kind"] == "izoh":
                covered[x["sense"]].append(r)
                note["sense"] = f"{x['sense']}-ma’no"
            elif x["kind"] == "birikma":
                note["sense"] = f"{x['sense']}-ma’no ichidagi birikma"
                ph = max((p for s in ent["senses"] for p in s["phrases"]), key=lambda p: pscore(clean_gloss(r.get("izoh")), p))
                add(r["_row"], soz, UZ["izoh"], XATO,
                    f"Ortiqcha sinset: bu lug‘atda «{used_entry}» so‘zining alohida ma’nosi emas, maqola ichidagi "
                    f"turg‘un birikma. Lug‘atda {nsen} ta ma’no — {nsen} ta sinset bo‘lishi kerak",
                    short(ph, 200), "Bu qator olib tashlansin")
            elif x["kind"] == "misol":
                note["sense"] = f"{x['sense']}-ma’no (misol)"
                s = next(s for s in ent["senses"] if s["n"] == x["sense"])
                add(r["_row"], soz, UZ["izoh"], XATO,
                    "Izoh ustuniga ma’no izohi emas, lug‘atdagi misol gap yozilgan",
                    f"{s['n']}-ma’no izohi: {short(s['gloss'], 200)}", "Izoh ustuniga lug‘atdagi ma’no izohi yozilsin")
            elif x["kind"] == "o'xshash":
                note["sense"] = f"{x['sense']}-ma’no (?)"
                s = next(s for s in ent["senses"] if s["n"] == x["sense"])
                covered[x["sense"]].append(r)
                add(r["_row"], soz, UZ["izoh"], KORIB,
                    f"Izoh lug‘atdagidan farq qiladi (o‘xshashlik {round(x['g_score'])}%) — o‘zgartirilgan yoki qisqartirilgan",
                    f"{s['n']}-ma’no: {short(s['gloss'], 200)}", "Lug‘at izohi bilan solishtirilsin")
            else:
                if is_empty(r.get("izoh")):
                    add(r["_row"], soz, UZ["izoh"], XATO, "Izoh (gloss) bo‘sh")
                else:
                    add(r["_row"], soz, UZ["izoh"], OGOH,
                        f"Izoh «{short(r.get('izoh'), 70)}» lug‘atdagi «{used_entry}» maqolasining hech bir "
                        f"ma’no izohiga mos kelmadi",
                        " | ".join(f"{s['n']}) {short(s['gloss'], 80)}" for s in ent["senses"]),
                        "Izoh qaysi manbadan olingani ko‘rsatilsin yoki lug‘at izohi yozilsin")

            # ---- misol gap ----
            ex = r.get("misol")
            if is_empty(ex):
                add(r["_row"], soz, UZ["misol"], XATO, "Misol gap yo‘q")
            else:
                exs = str(ex)
                stem = letters(used_entry[:-3] if used_entry.endswith("moq") else used_entry)
                stem = stem[:max(3, min(len(stem), 5))]
                if stem not in letters(exs) and letters(w)[:max(3, min(len(letters(w)), 5))] not in letters(exs):
                    add(r["_row"], soz, UZ["misol"], XATO, f"Misol gapda «{w}» so‘zi qatnashmagan", short(exs, 140),
                        "So‘z qatnashgan misol keltirilsin")
                if x["ex_score"] >= 75:
                    if x["kind"] in ("izoh", "o'xshash") and x["sense"] and x["ex_sense"] != x["sense"] \
                            and x["ex_score"] - x["ex_in_gloss_sense"] >= 15:
                        s2 = next(s for s in ent["senses"] if s["n"] == x["ex_sense"])
                        add(r["_row"], soz, UZ["misol"], XATO,
                            f"Misol gap boshqa ma’noga tegishli: izoh {x['sense']}-ma’no, misol esa lug‘atda "
                            f"{x['ex_sense']}-ma’no ostida berilgan",
                            f"{x['ex_sense']}-ma’no: {short(s2['gloss'], 150)}", f"{x['sense']}-ma’noning o‘z misoli olinsin")
                else:
                    has_src = bool(re.search(r"[A-ZА-Я]\.\s?[A-ZА-Я][a-zʻ'‘’]+|[“\"«][^”\"»]{3,}[”\"»]\s*\.?\s*$|Maqol|Gazetadan|OʻTA|O‘TA", exs))
                    if not has_src:
                        add(r["_row"], soz, UZ["misol"], KORIB,
                            "Misol gap lug‘atda topilmadi va manbasi (muallif/asar) ko‘rsatilmagan",
                            "", "Misol manbasi yozilsin yoki lug‘atdagi misol olinsin")
                key = letters(exs)[:80]
                if len(key) >= 20:
                    seen_examples[key].append((r["_row"], soz))

        # ---- ma'nolar qamrovi ----
        missing_s = [s for s in ent["senses"] if s["n"] not in covered]
        dup_s = {n: rs for n, rs in covered.items() if len(rs) > 1}
        if w in aset or not aset:
            for s in missing_s:
                add(grp[0]["_row"], w, UZ["izoh"], XATO,
                    f"«{used_entry}»: lug‘atdagi {s['n']}-ma’no uchun sinset tuzilmagan "
                    f"(lug‘atda {nsen} ta ma’no, talabada {len(grp)} ta qator)",
                    f"{s['n']}-ma’no: {short(s['gloss'], 200)}", "Shu ma’no uchun alohida qator qo‘shilsin")
        for n, rs in dup_s.items():
            add(rs[1]["_row"], str(rs[1].get("soz")), UZ["izoh"], OGOH,
                f"Lug‘atdagi {n}-ma’no ikki marta sinset qilingan (qatorlar: {', '.join(str(x['_row']) for x in rs)})",
                "", "Takror qator birlashtirilsin")
        if ent.get("missing_numbers"):
            add(grp[0]["_row"], w, "", KORIB,
                f"OCR bazada «{used_entry}» maqolasining {ent['missing_numbers']} raqamli ma’nosi aniqlanmadi — "
                "ma’nolar soni qo‘lda (PDF bo‘yicha) tekshirilsin")

        # ---- raqamlash ----
        nums = [r["_n"] for r in grp]
        if len(grp) > 1 and any(n is None for n in nums):
            add(grp[0]["_row"], w, UZ["soz"], OGOH, "Ko‘p ma’noli so‘z qatorlari raqamlanmagan (so‘z_01, so‘z_02 …)")
        elif len(grp) > 1 and sorted(nums) != list(range(1, len(grp) + 1)):
            add(grp[0]["_row"], w, UZ["soz"], OGOH, f"Ma’no raqamlari ketma-ket emas: {nums}")

        # ---- turkum (lug'at belgisi bo'yicha) ----
        expect = None
        if used_entry.endswith("moq"):
            expect = "Fe'l"
        elif len(ent["labels"]) == 1:
            expect = next(iter(ent["labels"]))
        for r, x in zip(grp, m):
            pos = norm_word(r.get("turkum"))
            soz = str(r.get("soz") or "").strip()
            if is_empty(r.get("turkum")):
                add(r["_row"], soz, UZ["turkum"], XATO, "Turkum ko‘rsatilmagan")
            elif pos not in POS_OK:
                add(r["_row"], soz, UZ["turkum"], OGOH, f"Turkum nomi standart emas: «{r.get('turkum')}»", "",
                    "Ot / Sifat / Fe'l / Ravish / Son / Olmosh / Taqlid so'z …")
            elif expect and x["kind"] != "birikma" and POS_OK[pos] != expect \
                    and not (len(ent["labels"]) == 1 and len(ent["senses"]) > 1):
                add(r["_row"], soz, UZ["turkum"], OGOH,
                    f"Turkum «{r.get('turkum')}» deb berilgan, lug‘at belgisi bo‘yicha: {expect}",
                    f"Lug‘atdagi grammatik belgi: {', '.join(sorted(ent['labels'])) or '-moq shakli'}", "Turkum qayta ko‘rib chiqilsin")

        st = "To‘liq" if not missing_s and len(grp) == nsen else (
            "Ma’no yetishmaydi" if missing_s else "Ortiqcha qator bor")
        word_table.append([w, "+" if w in aset else "–", used_entry, nsen, len(grp),
                           ", ".join(str(s["n"]) for s in missing_s) or "—",
                           len(grp) - sum(1 for n in covered) if len(grp) > len(covered) else 0, st])

    for w in missing:
        ent = lugat.entry(w)
        word_table.append([w, "+", w, len(ent["senses"]) if ent else "", 0,
                           ", ".join(str(s["n"]) for s in ent["senses"]) if ent else "", 0, "ISHLANMAGAN"])

    # --- 4. takror misollar -------------------------------------------------- #
    for key, lst in seen_examples.items():
        if len(lst) > 1:
            add(lst[1][0], lst[1][1], UZ["misol"], XATO,
                f"Bir xil misol gap bir necha qatorda ishlatilgan (qatorlar: {', '.join(str(a) for a, _ in lst)})",
                "", "Har bir ma’noga o‘z misoli berilsin")

    # --- 5. munosabat ustunlari (qoidaga asoslangan) ------------------------- #
    rel_cols = ["sinonim", "antonim", "giperonim", "giponim", "xolonim", "meronim"]
    for i, r in enumerate(rows):
        w = r.get("_w") or ""
        soz = str(r.get("soz") or "").strip()
        ent = row_entry.get(i)
        for k in REQUIRED:
            if k in hdr and k not in ("soz", "izoh", "misol", "turkum") and (r.get(k) is None or str(r.get(k)).strip() == ""):
                add(r["_row"], soz, UZ[k], OGOH, f"«{UZ[k]}» katagi butunlay bo‘sh",
                    "", "Topilmasa «-» yoki «qat’iy yo‘q» deb yozilsin (taqdimot, 6-slayd)")
        items = {k: [norm_word(x) for x in split_items(r.get(k))] for k in rel_cols}
        if w in items["sinonim"]:
            add(r["_row"], soz, UZ["sinonim"], XATO, "Sinonim sifatida so‘zning o‘zi yozilgan")
        both = set(items["sinonim"]) & set(items["giperonim"])
        if both:
            add(r["_row"], soz, UZ["giperonim"], XATO,
                f"Bir xil birlik ham sinonim, ham giperonim: {', '.join(sorted(both))}", "",
                "Sinonim o‘rnini bosadi, giperonim kengroq tushuncha — bittasi qoldirilsin")
        both = set(items["sinonim"]) & set(items["giponim"])
        if both:
            add(r["_row"], soz, UZ["giponim"], XATO,
                f"Bir xil birlik ham sinonim, ham giponim: {', '.join(sorted(both))}")
        both = set(items["sinonim"]) & set(items["antonim"])
        if both:
            add(r["_row"], soz, UZ["antonim"], XATO, f"Bir xil birlik ham sinonim, ham antonim: {', '.join(sorted(both))}")
        for a, b in (("giponim", "xolonim"), ("giponim", "meronim"), ("giperonim", "xolonim"), ("xolonim", "meronim")):
            both = set(items[a]) & set(items[b])
            if both:
                add(r["_row"], soz, UZ[b], XATO,
                    f"«{UZ[a]}» va «{UZ[b]}» ustunlarida bir xil birlik: {', '.join(sorted(both))}", "",
                    "Tur–jins (giponim) va butun–qism (xolonim/meronim) munosabatlari ajratilsin")
        # sifat/ravish uchun "so'z + ot" ko'rinishidagi giponimlar — bular birikma
        pos = POS_OK.get(norm_word(r.get("turkum")), "")
        if pos in ("Sifat", "Ravish") and items["giponim"]:
            colloc = [x for x in items["giponim"] if letters(w)[:max(4, len(letters(w)) - 1)] in letters(x) and " " in x]
            if len(colloc) >= max(1, len(items["giponim"]) // 2):
                add(r["_row"], soz, UZ["giponim"], KORIB,
                    f"Giponim o‘rnida so‘z birikmalari berilgan: {short(r.get('giponim'), 90)}", "",
                    "«" + w + " + ot» birikmasi giponim emas — bu qo‘llanish misoli. Tur bo‘lmasa «-» qo‘yilsin")
                issues[-1]["ai_dup"] = True
        # sinonim/antonim lug'at matni bilan tasdiqlanadimi
        if ent:
            body = letters(" ".join(s["text"] for s in ent["senses"]))
            def in_body(x):
                lx = letters(x)
                lx2 = lx[:-3] if lx.endswith("moq") and len(lx) > 6 else lx
                return len(lx) >= 3 and (lx in body or lx2 in body)
            if items["sinonim"]:
                ok = [x for x in items["sinonim"] if in_body(x)]
                no = [x for x in items["sinonim"] if not in_body(x)]
                row_notes[i]["sin"] = "; ".join(([f"✓ {', '.join(ok)}"] if ok else []) + ([f"✗ {', '.join(no)}"] if no else []))
            if items["antonim"] and not any(in_body(x) for x in items["antonim"]):
                add(r["_row"], soz, UZ["antonim"], KORIB,
                    f"Antonim «{short(r.get('antonim'), 80)}» izohli lug‘at maqolasida (zid.) ko‘rsatilmagan", "",
                    "Qat’iy leksik antonim bo‘lmasa «-» qo‘yilsin (taqdimot, 13-slayd: antonimni majburan topmaslik)")
                issues[-1]["ai_dup"] = True

    # --- statistika ---------------------------------------------------------- #
    stats = {
        "student": student or "", "file": os.path.basename(path), "assigned": len(assigned),
        "done": len([w for w in assigned if w in done]) if assigned else len(done),
        "missing_words": missing, "extra_words": extra, "rows": len(rows),
        "expected_rows": sum(len(lugat.entry(w)["senses"]) for w in assigned if lugat.entry(w)) if assigned else "",
        XATO: sum(1 for x in issues if x["daraja"] == XATO),
        OGOH: sum(1 for x in issues if x["daraja"] == OGOH),
        KORIB: sum(1 for x in issues if x["daraja"] == KORIB),
    }
    # --- AI lingvist uchun so'rovlar (har bir qator + lug'at konteksti) -------- #
    ai_req = []
    for i, r in enumerate(rows):
        ent = row_entry.get(i)
        sn = row_sense.get(i)
        s = next((s for s in ent["senses"] if s["n"] == sn), None) if ent and sn else None
        w = r.get("_w") or ""
        ai_req.append({
            "qator": r["_row"], "soz": str(r.get("soz") or "").strip(),
            "royxatda_bor": (w in aset) if aset else None,
            "lugat_maqolasi": row_used.get(i), "moslik_turi": row_kind.get(i),
            "lugat_mano_raqami": sn,
            "lugat_izohi": s["gloss"] if s else None,
            "lugat_misollari": short(s["examples"], 700) if s else None,
            "lugatdagi_barcha_manolar": [f"{x['n']}) {short(x['gloss'], 160)}" for x in ent["senses"]] if ent else [],
            "lugat_birikmalari": [short(p, 160) for x in ent["senses"] for p in x["phrases"]] if ent else [],
            "lugat_grammatik_belgisi": sorted(ent["labels"]) if ent else [],
            "talaba": {k: (None if r.get(k) is None else str(r.get(k)).replace("\xa0", " ").strip())
                       for k in ("izoh", "misol", "turkum", "soha", "sinonim", "antonim", "giperonim",
                                 "giponim", "xolonim", "meronim")},
        })
    return issues, row_notes, word_table, stats, ai_req


# --------------------------------------------------------------------------- #
#  Excel hisobot
# --------------------------------------------------------------------------- #
FILL = {XATO: "F8D7DA", OGOH: "FFF3CD", KORIB: "DDEBF7"}
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def style_header(ws, row, ncol):
    for c in range(1, ncol + 1):
        cell = ws.cell(row, c)
        cell.font = Font(bold=True, color="FFFFFF", name="Arial", size=10)
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = BORDER


def set_widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


AI_BAHO = {"togri": ("✓ To‘g‘ri", "E2EFDA"), "qisman": ("◐ Qisman to‘g‘ri", "FFF3CD"),
           "notogri": ("✗ Noto‘g‘ri", "F8D7DA"), "tavsiya": ("＋ Bo‘sh qoldirilgan — to‘ldirish mumkin", "DDEBF7")}
AI_COLS = ["izoh", "misol", "turkum", "sinonim", "antonim", "giperonim", "giponim", "xolonim", "meronim"]


def ai_counts(ai):
    c = Counter()
    for q in (ai or {}).get("qatorlar", {}).values():
        for k in AI_COLS:
            if k in q and q[k].get("baho") in AI_BAHO:
                c[q[k]["baho"]] += 1
    return c


def write_ai_sheet(wb, sub, ai):
    ws = wb.create_sheet("AI lingvist", 2)
    head = ["Qator", "So‘z", "Qator bo‘yicha izoh"] + [UZ[k] for k in AI_COLS]
    ws.append(head)
    style_header(ws, 1, len(head))
    for i, r in enumerate(sub["rows"], 2):
        q = ai["qatorlar"].get(str(r["_row"]), {})
        ws.append([r["_row"], str(r.get("soz") or "").strip(), q.get("holat", "")])
        if q.get("holat"):
            ws.cell(i, 3).fill = PatternFill("solid", fgColor="E7E6E6")
        for j, k in enumerate(AI_COLS, 4):
            v = q.get(k)
            val = r.get(k)
            sval = "" if val is None else str(val).replace("\xa0", " ").strip()
            cell = ws.cell(i, j)
            if not v or v.get("baho") not in AI_BAHO:
                cell.value = (short(sval, 60) if k not in ("izoh", "misol") else "") if not q.get("holat") else ""
                cell.font = Font(name="Arial", size=9, color="808080")
            else:
                lab, col = AI_BAHO[v["baho"]]
                parts = []
                if k not in ("izoh", "misol") and not is_empty(val):
                    parts.append(f"«{short(sval, 90)}»")
                parts.append(lab + (": " + v["izoh"] if v.get("izoh") else ""))
                if v.get("tavsiya"):
                    parts.append("→ Tavsiya: " + v["tavsiya"])
                if v.get("ishonch") == "past":
                    parts.append("(AI ishonchi past — manba bilan tekshirilsin)")
                cell.value = "\n".join(parts)
                cell.fill = PatternFill("solid", fgColor=col)
                cell.font = Font(name="Arial", size=9)
        for c in range(1, len(head) + 1):
            cell = ws.cell(i, c)
            if c <= 3:
                cell.font = Font(name="Arial", size=9, bold=(c == 2))
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = BORDER
    set_widths(ws, [6, 14, 26, 30, 26, 22, 34, 30, 34, 34, 30, 30])
    ws.freeze_panes = "C2"


def write_report(out_path, sub, issues, row_notes, word_table, stats, ai=None):
    wb = Workbook()
    # ---- Xulosa ----
    ws = wb.active
    ws.title = "Xulosa"
    ws["A1"] = "Sinset topshirig‘i tekshiruvi"
    ws["A1"].font = Font(bold=True, size=14, name="Arial")
    info = [
        ("Talaba", stats["student"]), ("Fayl", stats["file"]),
        ("Berilgan so‘zlar", stats["assigned"]), ("Ishlangan so‘zlar", stats["done"]),
        ("Ishlanmagan so‘zlar", ", ".join(stats["missing_words"]) or "—"),
        ("Ro‘yxatda yo‘q so‘zlar", ", ".join(stats["extra_words"]) or "—"),
        ("Sinset qatorlari (talabada)", stats["rows"]),
        ("Lug‘at bo‘yicha kutilgan ma’nolar soni", stats["expected_rows"]),
        (None, None),
        ("XATO", stats[XATO]), ("OGOHLANTIRISH", stats[OGOH]), ("KO‘RIB CHIQISH", stats[KORIB]),
    ]
    if ai:
        c = ai_counts(ai)
        info += [(None, None), ("AI lingvist bahosi (kataklar soni)", ""),
                 ("✓ To‘g‘ri", c["togri"]), ("◐ Qisman to‘g‘ri", c["qisman"]), ("✗ Noto‘g‘ri", c["notogri"]),
                 ("＋ Bo‘sh, to‘ldirish mumkin", c["tavsiya"])]
    for i, (k, v) in enumerate(info, 3):
        if k is None:
            continue
        ws.cell(i, 1, k).font = Font(bold=True, name="Arial", size=10)
        c = ws.cell(i, 2, v)
        c.font = Font(name="Arial", size=10)
        c.alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
        if k in FILL:
            ws.cell(i, 1).fill = PatternFill("solid", fgColor=FILL[k])
    r0 = 3 + len(info) + 1
    legend = [
        ("Darajalar", ""),
        ("XATO", "Qoidaga ko‘ra aniq xato: so‘z ishlanmagan, lug‘atdagi ma’no tashlab ketilgan, birikma alohida sinset qilingan (lug‘atda nechta ma’no — shuncha sinset), izoh o‘rniga misol yozilgan va h.k."),
        ("OGOHLANTIRISH", "Katta ehtimol bilan xato, lekin o‘qituvchi qarori kerak: boshqa maqola ishlangan, izoh lug‘atda topilmadi, turkum mos emas, katak bo‘sh."),
        ("KO‘RIB CHIQISH", "Avtomatik hal qilib bo‘lmaydi: sinonim/antonim manbada tasdiqlanmadi, giponim o‘rnida birikma. Mazmuniy baho — o‘qituvchida."),
        ("AI lingvist", "«AI lingvist» varag‘i: turkum va munosabatlarning mazmuniy bahosi. Lug‘atda bo‘lmasa ham to‘g‘ri bo‘lsa «to‘g‘ri» deb belgilanadi, xato bo‘lsa tavsiya beriladi. Tavsiyalar AI fikri — lug‘atdan olingan manba emas."),
        ("Eslatma", "Lug‘at matni OCR qilingan baza (O‘zbek tilining izohli lug‘ati, 5 jild). OCR xatosi tufayli ayrim signallar noto‘g‘ri bo‘lishi mumkin — «Lug‘atda» ustunidagi matn bilan solishtiring."),
    ]
    for i, (k, v) in enumerate(legend):
        a = ws.cell(r0 + i, 1, k)
        a.font = Font(bold=True, name="Arial", size=10)
        if k in FILL:
            a.fill = PatternFill("solid", fgColor=FILL[k])
        b = ws.cell(r0 + i, 2, v)
        b.font = Font(name="Arial", size=10)
        b.alignment = Alignment(wrap_text=True, vertical="top")
    set_widths(ws, [38, 95])

    # ---- Xatolar ----
    ws = wb.create_sheet("Xatolar")
    head = ["№", "Qator", "So‘z", "Ustun", "Daraja", "Xato / kamchilik", "Lug‘atda", "Tavsiya"]
    ws.append(head)
    style_header(ws, 1, len(head))
    order = {XATO: 0, OGOH: 1, KORIB: 2}
    srt = sorted(issues, key=lambda x: (order[x["daraja"]], x["row"] if isinstance(x["row"], int) else 0))
    for i, it in enumerate(srt, 1):
        ws.append([i, it["row"], it["soz"], it["ustun"], it["daraja"], it["xato"], it["lugatda"], it["tavsiya"]])
        for c in range(1, len(head) + 1):
            cell = ws.cell(i + 1, c)
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = BORDER
        ws.cell(i + 1, 5).fill = PatternFill("solid", fgColor=FILL[it["daraja"]])
    set_widths(ws, [5, 7, 16, 15, 17, 60, 60, 45])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(head))}{len(srt) + 1}"

    # ---- Sinsetlar (talaba jadvali + belgilar) ----
    ws = wb.create_sheet("Sinsetlar")
    hv = [h for h in sub["header_vals"]]
    while hv and hv[-1] is None:
        hv.pop()
    n0 = len(hv)
    head = ["Qator"] + hv + ["Lug‘at ma’nosi", "Izoh mosligi, %", "Misol mosligi, %",
                             "Sinonim lug‘at maqolasida (✓ bor / ✗ yo‘q)", "Topilgan kamchiliklar"]
    ws.append(head)
    style_header(ws, 1, len(head))
    by_row = defaultdict(list)
    for it in issues:
        if isinstance(it["row"], int):
            by_row[it["row"]].append(it)
    col_of = {UZ[k]: c for k, c in sub["hdr"].items()}
    for i, (r, vals, note) in enumerate(zip(sub["rows"], sub["all_rows"], row_notes), 2):
        its = by_row.get(r["_row"], [])
        txt = "\n".join(f"[{x['daraja']}] {x['ustun']}: {x['xato']}" for x in its)
        ws.append([r["_row"]] + list(vals[:n0]) + [note["sense"], note["g"], note["e"], note["sin"], txt])
        for c in range(1, len(head) + 1):
            cell = ws.cell(i, c)
            cell.font = Font(name="Arial", size=9)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = BORDER
        for x in sorted(its, key=lambda x: -order[x["daraja"]]):
            c = col_of.get(x["ustun"])
            if c and c <= n0:
                ws.cell(i, c + 1).fill = PatternFill("solid", fgColor=FILL[x["daraja"]])
        if its:
            worst = min(its, key=lambda x: order[x["daraja"]])["daraja"]
            ws.cell(i, len(head)).fill = PatternFill("solid", fgColor=FILL[worst])
    widths = [6] + [14] * n0 + [16, 9, 9, 30, 70]
    for k, c in sub["hdr"].items():
        if c <= n0:
            widths[c] = {"izoh": 38, "misol": 45, "soz": 14, "sinonim": 20, "giponim": 26}.get(k, 16)
    set_widths(ws, widths)
    ws.freeze_panes = "C2"

    # ---- So'zlar ----
    ws = wb.create_sheet("So‘zlar")
    head = ["So‘z", "Ro‘yxatda", "Lug‘at maqolasi", "Lug‘atda ma’nolar", "Talabada qatorlar",
            "Qoldirilgan ma’nolar", "Ma’noga bog‘lanmagan qatorlar", "Holat"]
    ws.append(head)
    style_header(ws, 1, len(head))
    for i, row in enumerate(word_table, 2):
        ws.append(row)
        for c in range(1, len(head) + 1):
            cell = ws.cell(i, c)
            cell.font = Font(name="Arial", size=10)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        st = row[-1]
        col = {"To‘liq": "E2EFDA", "ISHLANMAGAN": FILL[XATO], "Ma’no yetishmaydi": FILL[XATO],
               "Ortiqcha qator bor": FILL[OGOH]}.get(st, FILL[KORIB])
        ws.cell(i, len(head)).fill = PatternFill("solid", fgColor=col)
    set_widths(ws, [18, 10, 18, 12, 12, 16, 16, 20])
    ws.freeze_panes = "A2"
    if ai:
        write_ai_sheet(wb, sub, ai)
    wb.save(out_path)


def write_summary(out_path, all_stats):
    wb = Workbook()
    ws = wb.active
    ws.title = "Umumiy"
    head = ["Guruh", "Talaba", "Holat", "Fayl", "Berilgan so‘z", "Ishlangan", "Ishlanmagan so‘zlar",
            "Ro‘yxatda yo‘q so‘zlar", "Qatorlar", "Kutilgan ma’nolar", "XATO", "OGOHLANTIRISH", "KO‘RIB CHIQISH"]
    ws.append(head)
    style_header(ws, 1, len(head))
    for s in all_stats:
        if s.get("holat", "Tekshirildi") != "Tekshirildi":
            ws.append([s.get("guruh", ""), s["student"], s["holat"]])
            ws.cell(ws.max_row, 3).fill = PatternFill("solid", fgColor=FILL[XATO])
            continue
        ws.append([s.get("guruh", ""), s["student"], "Tekshirildi", s["file"], s["assigned"], s["done"],
                   ", ".join(s["missing_words"]), ", ".join(s["extra_words"]), s["rows"], s["expected_rows"],
                   s[XATO], s[OGOH], s[KORIB]])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Arial", size=10)
            cell.border = BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    set_widths(ws, [8, 40, 34, 42, 10, 10, 26, 26, 9, 11, 8, 16, 15])
    ws.freeze_panes = "A2"
    wb.save(out_path)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="UzWordNet sinset topshiriqlarini tekshirish")
    ap.add_argument("files", nargs="+", help="talaba .xlsx fayllari")
    ap.add_argument("--lugat", required=True)
    ap.add_argument("--sozlar", required=True)
    ap.add_argument("--chiqish", default="hisobot")
    ap.add_argument("--guruh", nargs="*", default=[], help="guruh ro‘yxati fayllari (201-guruh.txt ...)")
    ap.add_argument("--ai-sorov", help="AI lingvist uchun so‘rov JSON fayllari yoziladigan papka")
    ap.add_argument("--ai-javob", help="AI lingvist javoblari (<fayl>_AI.json) turgan papka")
    a = ap.parse_args()

    lugat = Lugat(a.lugat)
    wordlists = load_wordlists(a.sozlar)
    os.makedirs(a.chiqish, exist_ok=True)
    all_stats = []
    for f in a.files:
        student, sc = find_student(f, wordlists)
        assigned = wordlists[student]["words"] if student else []
        try:
            sub = read_submission(f)
        except Exception as e:  # noqa
            print(f"[!] {os.path.basename(f)}: o‘qib bo‘lmadi — {e}")
            continue
        issues, notes, wt, stats, ai_req = check_submission(f, sub, assigned, lugat,
                                                            student or "ANIQLANMADI (fayl nomidan)")
        base = os.path.splitext(os.path.basename(f))[0]
        if a.ai_sorov:
            os.makedirs(a.ai_sorov, exist_ok=True)
            with open(os.path.join(a.ai_sorov, base + "_SOROV.json"), "w", encoding="utf-8") as fh:
                json.dump({"talaba": stats["student"], "fayl": stats["file"], "qatorlar": ai_req}, fh,
                          ensure_ascii=False, indent=1)
        ai = None
        if a.ai_javob and os.path.exists(os.path.join(a.ai_javob, base + "_AI.json")):
            with open(os.path.join(a.ai_javob, base + "_AI.json"), encoding="utf-8") as fh:
                ai = json.load(fh)
            # AI baholagan kataklar bo'yicha qoidaviy "ko'rib chiqish" signallari takrorlanmaydi
            issues = [x for x in issues if not x.get("ai_dup")]
            stats[KORIB] = sum(1 for x in issues if x["daraja"] == KORIB)
        out = os.path.join(a.chiqish, base + "_TEKSHIRUV.xlsx")
        write_report(out, sub, issues, notes, wt, stats, ai)
        all_stats.append(stats)
        print(f"{stats['student']}: so‘z {stats['done']}/{stats['assigned']}, qator {stats['rows']} "
              f"(kutilgan {stats['expected_rows']}), XATO {stats[XATO]}, OGOH {stats[OGOH]}, KO‘RIB {stats[KORIB]} -> {out}")
    if a.guruh:
        by_student = {s["student"]: s for s in all_stats}
        full = []
        for g in a.guruh:
            gname = re.sub(r"^[0-9a-f]{6,}-", "", os.path.splitext(os.path.basename(g))[0])
            with open(g, encoding="utf-8") as fh:
                for name in (x.strip() for x in fh if x.strip()):
                    if name in by_student:
                        full.append(dict(by_student.pop(name), guruh=gname, holat="Tekshirildi"))
                    elif name not in wordlists:
                        full.append({"guruh": gname, "student": name, "holat": "So‘z ro‘yxati berilmagan — 0 ball"})
                    else:
                        full.append({"guruh": gname, "student": name, "holat": "Fayl topshirilmagan"})
        full += [dict(s, holat="Tekshirildi") for s in by_student.values()]
        all_stats = full
    if a.guruh or len(all_stats) > 1:
        write_summary(os.path.join(a.chiqish, "UMUMIY_XULOSA.xlsx"), all_stats)


if __name__ == "__main__":
    sys.exit(main())
