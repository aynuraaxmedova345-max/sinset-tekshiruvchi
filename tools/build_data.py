#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Veb-sahifa uchun ma'lumot fayllarini tayyorlaydi: web/data.json va (ixtiyoriy) web/namuna.json.

data.json ichiga kiradi:
  - talabalarga berilgan so'zlar ro'yxati (--sozlar papkasidagi .txt fayllar);
  - guruh ro'yxatlari (--guruh fayllari);
  - faqat shu so'zlarga tegishli izohli lug'at maqolalari (--lugat bazasidan, ma'nolarga ajratilgan holda).

DIQQAT: data.json talabalar ismlari va lug'at matnini o'z ichiga oladi, shuning uchun u .gitignore'da.
Uni repozitoriyga qo'shmang.

Misol (repo ichidagi namuna bilan):
    python tools/build_data.py --lugat dictionary.sqlite \
        --sozlar samples/sozlar --guruh samples/guruh/201-guruh.txt \
        --namuna samples/Namuna_Talaba_201.xlsx --namuna-ai samples/Namuna_Talaba_201_AI.json \
        --chiqish web
"""
import argparse
import json
import os
import sys

import openpyxl

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
import sinset_tekshiruvchi as t  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="web/data.json va web/namuna.json ni tayyorlash")
    ap.add_argument("--lugat", required=True, help="izohli lug'at OCR bazasi (dictionary.sqlite)")
    ap.add_argument("--sozlar", required=True, help="har bir talabaga berilgan so'zlar (.txt) papkasi")
    ap.add_argument("--guruh", nargs="+", required=True, help="guruh ro'yxati fayllari: 201-guruh.txt ...")
    ap.add_argument("--chiqish", default="web", help="natija papkasi (standart: web)")
    ap.add_argument("--namuna", help="sahifa birinchi ochilganda ko'rsatiladigan namuna .xlsx (ixtiyoriy)")
    ap.add_argument("--namuna-ai", help="namuna uchun AI lingvist javobi .json (ixtiyoriy)")
    a = ap.parse_args()

    lugat = t.Lugat(a.lugat)
    wordlists = t.load_wordlists(a.sozlar)
    need = set()
    for info in wordlists.values():
        for w in info["words"]:
            need.add(w)
            for alt in (w + "moq", w[:-3] if w.endswith("moq") else None, w + "lik", w + "li"):
                if alt and lugat.has(alt):
                    need.add(alt)
    lug = {}
    for w in sorted(need):
        e = lugat.entry(w)
        if e:
            lug[w] = {"s": [{"n": s["n"], "g": s["gloss"], "e": s["examples"], "p": s["phrases"], "t": s["text"]}
                            for s in e["senses"]],
                      "l": sorted(e["labels"]), "m": e["missing_numbers"]}
    topilmadi = sorted(w for info in wordlists.values() for w in info["words"] if w not in lug)

    guruh = {}
    for g in a.guruh:
        nom = os.path.splitext(os.path.basename(g))[0].split("-")[0]
        with open(g, encoding="utf-8") as fh:
            guruh[nom] = [x.strip() for x in fh if x.strip()]

    os.makedirs(a.chiqish, exist_ok=True)
    data = {"lugat": lug, "sozlar": {k: v["words"] for k, v in wordlists.items()}, "guruh": guruh,
            "lugat_nomi": "O‘zbek tilining izohli lug‘ati (5 jild), OCR baza"}
    out = os.path.join(a.chiqish, "data.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"{out}: {len(wordlists)} talaba, {len(lug)} lug‘at maqolasi, {os.path.getsize(out) // 1024} KB")
    if topilmadi:
        print(f"  ogohlantirish: {len(topilmadi)} so‘z lug‘atda topilmadi: {', '.join(topilmadi[:20])}")

    if a.namuna:
        wb = openpyxl.load_workbook(a.namuna, data_only=True)
        varaqlar = [{"nom": ws.title, "grid": [list(r) for r in ws.iter_rows(values_only=True)]} for ws in wb.worksheets]
        ai = {}
        if a.namuna_ai:
            with open(a.namuna_ai, encoding="utf-8") as fh:
                ai = json.load(fh).get("qatorlar", {})
        out2 = os.path.join(a.chiqish, "namuna.json")
        with open(out2, "w", encoding="utf-8") as fh:
            json.dump({"fayl": os.path.basename(a.namuna), "varaqlar": varaqlar, "ai": ai}, fh,
                      ensure_ascii=False, separators=(",", ":"), default=str)
        print(f"{out2}: namuna tayyor")


if __name__ == "__main__":
    main()
