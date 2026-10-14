# Sinset tekshiruvchi

Talabalarning **UzWordNet sinset topshiriqlarini** «O‘zbek tilining izohli lug‘ati» asosida avtomatik tekshiradigan vosita.
Talabaning Excel fayli yuklanadi, har bir sinset lug‘at bilan solishtiriladi, natijada ball, umumiy feedback,
talabaga yuboriladigan Excel va guruh bo‘yicha Word baholash jadvali chiqadi.

*An automatic checker for students' Uzbek WordNet synset assignments: each synset is compared against the Uzbek
explanatory dictionary (rule layer), relations and part of speech are judged by an LLM "linguist" (AI layer),
and results are exported as per-student Excel files and a group-level Word grading table.*

## Nima tekshiriladi

**1. Qoidaviy qatlam** (`web/engine.js`, `python/sinset_tekshiruvchi.py`):

- berilgan 50 ta so‘zning hammasi ishlanganmi, ro‘yxatda yo‘q so‘z bormi;
- lug‘atdagi har bir ma’noga alohida sinset tuzilganmi (qoida: **lug‘atda nechta ma’no — shuncha sinset**);
- turg‘un birikma alohida sinset qilinmaganmi;
- izoh lug‘atdagi ma’noga mosmi, izoh o‘rniga misol yozilmaganmi;
- misol gap o‘sha ma’noga tegishlimi, takrorlanmaganmi, so‘z qatnashganmi;
- turkum lug‘at belgisiga mosmi;
- sinonim–giperonim, giponim–xolonim aralashmaganmi.

**2. AI lingvist** (`python/ai_lingvist_prompt.md`): turkum, sinonim, antonim, giperonim, giponim, xolonim va meronim
kataklarini mazmunan baholaydi. Birlik lug‘atda bo‘lmasa ham to‘g‘ri bo‘lsa «to‘g‘ri» deydi, xato bo‘lsa tavsiya beradi.
AI tavsiyalari — AI fikri, lug‘at manbasi emas.

## Tuzilma

```
web/            brauzer ilovasi (index.html + engine.js); data.json build_data.py bilan yaratiladi
python/         buyruq satri versiyasi va AI lingvist ko‘rsatmasi
tools/          build_data.py — web/data.json va web/namuna.json ni tayyorlaydi
samples/        ismsiz bitta namuna: talaba fayli, uning so‘z ro‘yxati, guruh va AI javobi
```

## Ma’lumotlar va maxfiylik

Repozitoriyda **talabalar fayllari, ismlari, so‘z ro‘yxatlari va lug‘at bazasi yo‘q**. Ular faqat sizning kompyuteringizda
turadi va `.gitignore` orqali yopilgan (`web/data.json`, `*.sqlite`, `*.xlsx`, `*.docx`).
`samples/` ichidagi namuna ismsizlashtirilgan.

Lug‘at bazasi: [jasurshukurov/izohli_lugat](https://github.com/jasurshukurov/izohli_lugat) repozitoriyidagi
`app/src/main/assets/dictionary.sqlite` (5 jildlik izohli lug‘atning OCR matni, 31 126 maqola).

## Ishga tushirish

### 1. Lug‘at bazasini yuklab olish

```bash
git clone --depth 1 https://github.com/jasurshukurov/izohli_lugat.git
cp izohli_lugat/app/src/main/assets/dictionary.sqlite .
pip install -r python/requirements.txt
```

### 2. Ma’lumotlarni tayyorlash

So‘z ro‘yxatlari: har bir talabaga bitta `.txt`, nomi `NN_FAMILIYA_ISM_OTASI_QIZI.txt`, ichida qatorma-qator so‘zlar.
Guruh ro‘yxati: `201-guruh.txt`, ichida qatorma-qator to‘liq ismlar.

```bash
python tools/build_data.py --lugat dictionary.sqlite \
    --sozlar sozlar/ --guruh guruh/201-guruh.txt guruh/202-guruh.txt --chiqish web
```

Namuna bilan sinab ko‘rish:

```bash
python tools/build_data.py --lugat dictionary.sqlite --sozlar samples/sozlar \
    --guruh samples/guruh/201-guruh.txt --namuna samples/Namuna_Talaba_201.xlsx \
    --namuna-ai samples/Namuna_Talaba_201_AI.json --chiqish web
```

### 3a. Brauzer ilovasi

```bash
cd web && python -m http.server 8000      # keyin http://localhost:8000
```

Talaba fayllarini sahifaga tashlang. Talaba fayl nomidagi familiyadan aniqlanadi. Yuklanganlar shu brauzerning
o‘zida (IndexedDB) saqlanadi va hech qayerga yuborilmaydi. Tugmalar:

- **Talaba uchun Excel** — faqat shu talabaning bali, feedbacki va xatolari;
- **Bitta Excel qilib yuklab olish** — barcha talabalar bitta faylda;
- **Word jadval** — umumlashtirilgan baholash jadvali va kamchilik turlari bo‘yicha taqsimot.

AI lingvist tugmasi sahifa claude.ai’da Artifact sifatida ochilganda ishlaydi (Claude so‘rovlari foydalanuvchi hisobidan).
Oddiy brauzerda qoidaviy tekshiruv, ball va barcha eksportlar ishlaydi.

### 3b. Buyruq satri

```bash
python python/sinset_tekshiruvchi.py --lugat dictionary.sqlite --sozlar sozlar/ \
    --guruh guruh/*.txt --chiqish hisobot/ --ai-sorov ai_sorov/ talabalar/*.xlsx
```

Har bir talaba uchun `*_TEKSHIRUV.xlsx`, oxirida `UMUMIY_XULOSA.xlsx` chiqadi.
`--ai-sorov` har bir qator uchun lug‘at konteksti bilan JSON so‘rov yozadi; ularni `ai_lingvist_prompt.md` bilan
istalgan LLM’ga yuborib, javoblarni `<fayl>_AI.json` qilib `--ai-javob` papkasiga qo‘ysangiz, hisobotga «AI lingvist» varag‘i qo‘shiladi.

## Baholash

| Ko‘rsatkich | Hisob |
|---|---|
| Xato ulushi | tuzilmaviy xatosi bor qatorlar / barcha qatorlar |
| Umumiy ko‘rsatkich | 100% − xato ulushi |
| Qamrov | lug‘atdagi ma’nolardan nechtasiga sinset tuzilgan |
| Mazmun (AI) | to‘g‘ri = 1, qisman = 0,5, noto‘g‘ri = 0 |

Word jadvaldagi baho umumiy ko‘rsatkich bo‘yicha qo‘yiladi: **90–100% — 5; 70–89,9% — 4; 50–69,9% — 3; 50% dan past — 2.**
Sahifadagi 100 ballik ball esa uch qismning og‘irlikli o‘rtachasi (qamrov 40, izoh va misol 20, mazmun 40), sozlamalarda o‘zgartiriladi.

## Cheklovlar

- Lug‘at matni OCR qilingan: ayrim maqolalarda ma’no raqamlari o‘qilmagan (hisobotda «ko‘rib chiqish» deb belgilanadi).
- Talaba izohni boshqa manbadan (masalan, izoh.uz yangi nashri) olgan bo‘lsa, qatorlar xato deb sanalishi mumkin —
  juda yuqori xato ulushini qo‘lda tekshiring.

## Muallif

Aynura Axmedova — Alisher Navoiy nomidagi Toshkent davlat o‘zbek tili va adabiyoti universiteti, kompyuter lingvistikasi.
