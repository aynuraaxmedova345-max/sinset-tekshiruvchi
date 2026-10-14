/* Sinset tekshiruvchi — brauzer dvigateli (qoidalar, ball, feedback, AI so'rov/javob).
   Sahifada <script src="engine.js"> orqali `SinsetEngine` global obyekti sifatida, Node'da require() orqali ishlaydi. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SinsetEngine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const XATO = "XATO", OGOH = "OGOHLANTIRISH", KORIB = "KO‘RIB CHIQISH";
  const APOS = /[ʻʼ‘’`´'ʹʽ]/g;

  // ---------------------------------------------------------------- normalizatsiya
  function normWord(w) {
    return String(w == null ? "" : w).replace(/ /g, " ").trim().toLowerCase().replace(APOS, "'").replace(/\s+/g, " ");
  }
  function letters(s) {
    s = String(s == null ? "" : s).toLowerCase().replace(APOS, "");
    s = s.split("sh.k.").join("shukabi").split("sh. k.").join("shukabi").split("shu kabilar").join("shukabi").split("shu kabi").join("shukabi");
    return s.replace(/[^a-zа-яёқғҳў]/g, "");
  }
  function baseWord(cell) {
    const s = String(cell == null ? "" : cell).replace(/ /g, " ").trim();
    const m = s.match(/^(.*?)[\s_.\-]*(?:\.?[a-z]\.)?[_.\-\s]*\(?(\d{1,2})\)?$/);
    if (m && m[1].trim()) return [normWord(m[1]), parseInt(m[2], 10)];
    return [normWord(s), null];
  }
  const FILLER = /\s*(degan\s+)?ma['ʻʼ‘’]?no(lar)?(i|ini|sini|larini)?\s+(bildiradi|anglatadi)\.?\s*$/i;
  function cleanGloss(g) {
    return String(g == null ? "" : g).replace(/ /g, " ").trim().replace(FILLER, "").trim();
  }
  function isEmpty(v) {
    if (v == null) return true;
    const s = String(v).replace(/ /g, " ").trim();
    return s === "" || s === "-" || s === "–" || s === "—" || s === "yo'q" || s === "yoʻq" || s === "yo‘q";
  }
  function short(s, n) {
    n = n || 170;
    s = String(s == null ? "" : s).replace(/\s+/g, " ").trim();
    return s.length <= n ? s : s.slice(0, n).replace(/\s+$/, "") + "…";
  }
  function cellStr(v) {
    return v == null ? "" : String(v).replace(/ /g, " ").trim();
  }

  // ---------------------------------------------------------------- o'xshashlik
  // Qisqa satrning uzun satr ichidagi eng yaxshi bo'lagiga o'xshashligi (0..100), indel masofasi asosida.
  function partial(a, b) {
    let p = a, t = b;
    if (p.length > t.length) { p = b; t = a; }
    const m = p.length, n = t.length;
    if (!m) return 0;
    let prevD = new Int32Array(m + 1), prevS = new Int32Array(m + 1);
    let curD = new Int32Array(m + 1), curS = new Int32Array(m + 1);
    for (let i = 0; i <= m; i++) { prevD[i] = i; prevS[i] = 0; }
    const pc = new Uint16Array(m);
    for (let i = 0; i < m; i++) pc[i] = p.charCodeAt(i);
    let best = 0;
    for (let j = 1; j <= n; j++) {
      const c = t.charCodeAt(j - 1);
      curD[0] = 0; curS[0] = j;
      for (let i = 1; i <= m; i++) {
        if (pc[i - 1] === c) { curD[i] = prevD[i - 1]; curS[i] = prevS[i - 1]; }
        else {
          const up = curD[i - 1] + 1, left = prevD[i] + 1;
          if (up <= left) { curD[i] = up; curS[i] = curS[i - 1]; }
          else { curD[i] = left; curS[i] = prevS[i]; }
        }
      }
      const len = j - curS[m];
      const sc = 1 - curD[m] / (m + len);
      if (sc > best) best = sc;
      const td = prevD; prevD = curD; curD = td;
      const ts = prevS; prevS = curS; curS = ts;
    }
    return best * 100;
  }
  function pscore(a, b) {
    const la = letters(a), lb = letters(b);
    if (la.length < 6 || lb.length < 6) return 0;
    return partial(la, lb);
  }
  function lcsLen(a, b) {
    const m = a.length, n = b.length;
    let prev = new Int32Array(n + 1), cur = new Int32Array(n + 1);
    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) cur[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], cur[j - 1]);
      const t = prev; prev = cur; cur = t;
    }
    return prev[n];
  }
  function ratio(a, b) {
    if (!a.length && !b.length) return 100;
    return 200 * lcsLen(a, b) / (a.length + b.length);
  }

  // ---------------------------------------------------------------- talaba jadvali
  const COLS = {
    soz: ["so'z", "soz", "lemma", "synset id", "sinset id"], sinonim: ["sinonim"], izoh: ["izoh", "gloss"],
    misol: ["misol"], turkum: ["turkum", "pos"], soha: ["soha"], antonim: ["antonim"], giperonim: ["giperonim"],
    giponim: ["giponim"], xolonim: ["xolonim", "holonim"], meronim: ["meronim"],
  };
  const REQUIRED = ["soz", "sinonim", "izoh", "misol", "turkum", "soha", "antonim", "giperonim", "giponim", "xolonim", "meronim"];
  const UZ = { soz: "So‘z", sinonim: "Sinonimlari", izoh: "Izohi (gloss)", misol: "Misol gap", turkum: "Turkumi", soha: "Sohasi",
    antonim: "Antonimi", giperonim: "Giperonimi", giponim: "Giponimlari", xolonim: "Xolonimi", meronim: "Meronimi" };

  /** varaqlar: [{nom, grid: [[...], ...]}] -> {sheet, hdr, rows} yoki xato tashlaydi */
  function readSubmission(varaqlar) {
    let best = null;
    for (const v of varaqlar) {
      const g = v.grid || [];
      for (let r = 0; r < Math.min(g.length, 15); r++) {
        const hdr = {}; let cnt = 0;
        const row = g[r] || [];
        for (let c = 0; c < Math.min(row.length, 30); c++) {
          if (row[c] == null) continue;
          const key = normWord(row[c]);
          for (const name in COLS) {
            if (!(name in hdr) && COLS[name].some(a => key.startsWith(a))) { hdr[name] = c; cnt++; }
          }
        }
        if (cnt >= 4 && (!best || cnt > best.cnt)) best = { v, r, hdr, cnt };
      }
    }
    if (!best) throw new Error("Jadval sarlavhasi topilmadi: «So‘z», «Izohi», «Misol gap» ustunlari bo‘lishi kerak");
    const rows = [];
    const g = best.v.grid;
    for (let r = best.r + 1; r < g.length; r++) {
      const rec = {}; let any = false;
      for (const k in best.hdr) {
        const val = (g[r] || [])[best.hdr[k]];
        rec[k] = val == null ? null : val;
        if (val != null && String(val).trim() !== "") any = true;
      }
      if (!any) continue;
      rec._row = r + 1;
      rows.push(rec);
    }
    return { sheet: best.v.nom, hdr: best.hdr, rows };
  }

  // ---------------------------------------------------------------- talabani fayl nomidan aniqlash
  const NAME_SKIP = new Set(["qizi", "ogli", "gr", "guruh", "wordnet", "klwordnet", "kl", "xlsx", "sinset", "uzwordnet"]);
  function nameKey(s) {
    return normWord(s).replace(/'/g, "").replace(/[^a-z]+/g, " ").split(" ").filter(t => t && !NAME_SKIP.has(t));
  }
  function findStudent(fileName, names) {
    const toks = nameKey(String(fileName).replace(/\.[^.]+$/, ""));
    let best = null, bestSc = 0;
    for (const full of names) {
      const key = nameKey(full);
      const fam = key[0] || "", ism = key[1] || "";
      let f = 0, i = 0;
      for (const t of toks) { f = Math.max(f, ratio(fam, t)); i = Math.max(i, ratio(ism, t)); }
      const sc = 0.6 * f + 0.4 * i;
      if (f >= 85 && sc > bestSc) { best = full; bestSc = sc; }
    }
    return best;
  }

  // ---------------------------------------------------------------- qatorlarni ma'nolarga bog'lash
  function maxBy(list) { // [[score, n], ...] -> eng yuqori ball; teng bo'lsa katta n
    let b = [0, null];
    let first = true;
    for (const x of list) {
      if (first || x[0] > b[0] || (x[0] === b[0] && x[1] > b[1])) { b = x; first = false; }
    }
    return b;
  }
  function matchRows(rows, ent) {
    const res = [];
    for (const r of rows) {
      const g = cleanGloss(r.izoh);
      const lg = letters(g).length;
      const info = { sense: null, g: 0, kind: "yo'q", exSense: null, ex: 0, exIn: 0 };
      if (ent && ent.s.length && lg >= 6) {
        let bg = maxBy(ent.s.map(s => [pscore(g, s.g), s.n]));
        let be = maxBy(ent.s.filter(s => s.e).map(s => [pscore(g, s.e), s.n]));
        const ph = [];
        for (const s of ent.s) for (const p of s.p) ph.push([pscore(g, p), s.n]);
        let bp = maxBy(ph);
        let bt = maxBy(ent.s.map(s => [pscore(g, s.g + " " + s.e), s.n]));
        if (lg < 12) { be = [0, null]; bp = [0, null]; bt = [0, null]; if (bg[0] < 90) bg = [0, null]; }
        if (bg[0] >= 78 && bg[0] >= Math.max(be[0], bp[0]) - 6) { info.sense = bg[1]; info.g = bg[0]; info.kind = "izoh"; }
        else if (bp[0] >= 78 && bp[0] > be[0]) { info.sense = bp[1]; info.g = bp[0]; info.kind = "birikma"; }
        else if (be[0] >= 80 && lg >= 20) { info.sense = be[1]; info.g = be[0]; info.kind = "misol"; }
        else if (bt[0] >= 78 && lg >= 25) { info.sense = bt[1]; info.g = bt[0]; info.kind = "izoh"; }
        else if (Math.max(bg[0], bp[0]) >= 60) { const top = bg[0] >= bp[0] ? bg : bp; info.sense = top[1]; info.g = top[0]; info.kind = "o'xshash"; }
        else info.g = Math.max(bg[0], bp[0], be[0]);
      }
      const ex = r.misol;
      if (ent && ent.s.length && letters(ex).length >= 10) {
        const be = maxBy(ent.s.map(s => [pscore(ex, s.t), s.n]));
        info.ex = be[0]; info.exSense = be[0] >= 75 ? be[1] : null;
        if (info.sense != null) { const s = ent.s.find(s => s.n === info.sense); if (s) info.exIn = pscore(ex, s.t); }
      }
      res.push(info);
    }
    return res;
  }

  const POS_OK = { "ot": "Ot", "sifat": "Sifat", "fe'l": "Fe'l", "fel": "Fe'l", "ravish": "Ravish", "son": "Son", "olmosh": "Olmosh",
    "taqlid so'z": "Taqlid so'z", "taqlid": "Taqlid so'z", "undov": "Undov", "undov so'z": "Undov", "modal so'z": "Modal so'z",
    "modal": "Modal so'z", "ko'makchi": "Ko'makchi", "bog'lovchi": "Bog'lovchi", "yuklama": "Yuklama",
    "noun": "Ot", "verb": "Fe'l", "adj": "Sifat", "adv": "Ravish" };
  function splitItems(cell) {
    if (isEmpty(cell)) return [];
    return String(cell).replace(/ /g, " ").split(/[;,/]/).map(x => x.trim()).filter(x => x && x !== "-");
  }
  function inter(a, b) { const sb = new Set(b); return [...new Set(a.filter(x => sb.has(x)))].sort(); }

  // ---------------------------------------------------------------- asosiy tekshiruv
  /** lugat: {soz: {s:[{n,g,e,p,t}], l:[], m:[]}} ; assigned: [so'zlar] yoki [] */
  function check(sub, assigned, lugat) {
    const issues = [];
    const rows = sub.rows, hdr = sub.hdr;
    const add = (row, soz, ustun, daraja, kod, xato, lugatda, tavsiya, aiDup) =>
      issues.push({ row, soz, ustun, daraja, kod, xato, lugatda: lugatda || "", tavsiya: tavsiya || "", aiDup: !!aiDup });
    const entry = w => lugat[w] || null;

    for (const k of REQUIRED) if (!(k in hdr)) add("", "", UZ[k], XATO, "ustun", `«${UZ[k]}» ustuni jadvalda yo‘q`, "", "Namuna shablonidagi ustunlar to‘liq bo‘lsin");

    const groups = new Map();
    rows.forEach((r, i) => {
      const [w, n] = baseWord(r.soz);
      r._w = w; r._n = n;
      if (!w) { add(r._row, "", UZ.soz, XATO, "soz_bosh", "So‘z ustuni bo‘sh"); return; }
      if (!groups.has(w)) groups.set(w, []);
      groups.get(w).push(i);
    });

    assigned = assigned || [];
    const aset = new Set(assigned);
    const missing = assigned.filter(w => !groups.has(w));
    const extra = aset.size ? [...groups.keys()].filter(w => !aset.has(w)) : [];
    const replaced = {};
    for (const w of extra) {
      let cand = null, sc = -1;
      for (const m of missing) { const r = ratio(w, m); if (r > sc) { sc = r; cand = m; } }
      if (cand && (sc >= 70 || cand + "moq" === w || w.startsWith(cand))) replaced[w] = cand;
    }
    for (const w of missing) {
      const ent = entry(w), nsen = ent ? ent.s.length : 0;
      const used = Object.keys(replaced).filter(k => replaced[k] === w);
      add("", w, UZ.soz, XATO, "soz_yoq", `Berilgan «${w}» so‘zi ishlanmagan` + (used.length ? ` (o‘rniga «${used[0]}» yozilgan)` : ""),
        `Lug‘atda ${nsen} ta ma’no: ` + (ent ? ent.s.map(s => `${s.n}) ${short(s.g, 90)}`).join(" | ") : ""), `«${w}» uchun ${nsen} ta sinset tuzilsin`);
    }
    for (const w of extra) {
      const i = groups.get(w)[0];
      add(rows[i]._row, w, UZ.soz, XATO, "soz_ortiqcha", `«${w}» so‘zi talabaga berilgan 50 ta so‘z ro‘yxatida yo‘q` + (replaced[w] ? ` (ehtimol «${replaced[w]}» o‘rniga)` : ""),
        "", "Berilgan ro‘yxatdagi so‘z ishlansin");
    }

    const wordTable = [];
    const notes = rows.map(() => ({ sense: "", g: "", e: "", sin: "", kind: "", senseN: null, used: null, skip: "" }));
    const rowEnt = {};
    const seenEx = new Map();
    let coveredAssigned = 0;

    for (const [w, idxs] of groups) {
      const grp = idxs.map(i => rows[i]);
      let ent = entry(w), used = w;
      let m = matchRows(grp, ent);
      let avg = m.reduce((a, x) => a + x.g, 0) / m.length;
      const alts = [w + "moq", w.endsWith("moq") ? w.slice(0, -3) : null, w + "lik", w + "li"].filter(a => a && lugat[a]);
      let wrongEntry = false;
      for (const a of alts) {
        const ma = matchRows(grp, entry(a));
        const avga = ma.reduce((s, x) => s + x.g, 0) / ma.length;
        if (avga > avg + 15 && avga >= 70) {
          const orig = ent;
          ent = entry(a); m = ma; avg = avga; used = a; wrongEntry = true;
          add(grp[0]._row, w, UZ.soz, OGOH, "boshqa_maqola", `Berilgan so‘z «${w}», lekin izohlar lug‘atdagi «${a}» maqolasidan olingan`,
            orig ? `«${w}»: ` + orig.s.map(s => short(s.g, 90)).join(" | ") : "", `Aynan «${w}» so‘zi ishlanishi kerakmi yoki «${a}» — o‘qituvchi aniqlashtirsin`);
        }
      }
      const inList = aset.has(w);
      if (!ent) {
        if (inList || !aset.size) add(grp[0]._row, w, UZ.soz, KORIB, "lugatda_yoq", `«${w}» so‘zi lug‘at bazasida topilmadi — qo‘lda tekshirilsin`);
        idxs.forEach(i => { notes[i].skip = inList ? "" : "Ro‘yxatda yo‘q so‘z — baholanmadi"; });
        wordTable.push([w, inList ? "+" : "–", used, "", grp.length, "", "", inList ? "Lug‘atda topilmadi" : "Ro‘yxatda yo‘q"]);
        continue;
      }
      const nsen = ent.s.length;
      const covered = new Map();
      grp.forEach((r, gi) => {
        const x = m[gi], i = idxs[gi];
        const soz = cellStr(r.soz), note = notes[i];
        rowEnt[i] = ent; note.kind = x.kind; note.senseN = x.sense; note.used = used;
        note.g = Math.round(x.g); note.e = Math.round(x.ex);
        if (!inList && aset.size) note.skip = "Ro‘yxatda yo‘q so‘z — baholanmadi";
        const cover = () => { if (!covered.has(x.sense)) covered.set(x.sense, []); covered.get(x.sense).push(r); };
        if (x.kind === "izoh") { cover(); note.sense = `${x.sense}-ma’no`; }
        else if (x.kind === "birikma") {
          note.sense = `${x.sense}-ma’no ichidagi birikma`;
          note.skip = "Ortiqcha qator (birikma) — baholanmadi";
          let ph = "", sc = -1; const cg = cleanGloss(r.izoh);
          for (const s of ent.s) for (const p of s.p) { const v = pscore(cg, p); if (v > sc) { sc = v; ph = p; } }
          add(r._row, soz, UZ.izoh, XATO, "birikma", `Ortiqcha sinset: bu lug‘atda «${used}» so‘zining alohida ma’nosi emas, maqola ichidagi turg‘un birikma. Lug‘atda ${nsen} ta ma’no — ${nsen} ta sinset bo‘lishi kerak`,
            short(ph, 200), "Bu qator olib tashlansin");
        } else if (x.kind === "misol") {
          note.sense = `${x.sense}-ma’no (misol)`;
          const s = ent.s.find(s => s.n === x.sense);
          add(r._row, soz, UZ.izoh, XATO, "izoh_misol", "Izoh ustuniga ma’no izohi emas, lug‘atdagi misol gap yozilgan",
            `${s.n}-ma’no izohi: ${short(s.g, 200)}`, "Izoh ustuniga lug‘atdagi ma’no izohi yozilsin");
        } else if (x.kind === "o'xshash") {
          note.sense = `${x.sense}-ma’no (?)`;
          const s = ent.s.find(s => s.n === x.sense);
          cover();
          add(r._row, soz, UZ.izoh, KORIB, "izoh_farq", `Izoh lug‘atdagidan farq qiladi (o‘xshashlik ${Math.round(x.g)}%) — o‘zgartirilgan yoki qisqartirilgan`,
            `${s.n}-ma’no: ${short(s.g, 200)}`, "Lug‘at izohi bilan solishtirilsin");
        } else if (isEmpty(r.izoh)) add(r._row, soz, UZ.izoh, XATO, "izoh_bosh", "Izoh (gloss) bo‘sh");
        else add(r._row, soz, UZ.izoh, OGOH, "izoh_topilmadi", `Izoh «${short(r.izoh, 70)}» lug‘atdagi «${used}» maqolasining hech bir ma’no izohiga mos kelmadi`,
          ent.s.map(s => `${s.n}) ${short(s.g, 80)}`).join(" | "), "Izoh qaysi manbadan olingani ko‘rsatilsin yoki lug‘at izohi yozilsin");

        // misol gap
        const ex = r.misol;
        if (isEmpty(ex)) add(r._row, soz, UZ.misol, XATO, "misol_bosh", "Misol gap yo‘q");
        else {
          const exs = String(ex), lex = letters(exs);
          let stem = letters(used.endsWith("moq") ? used.slice(0, -3) : used);
          stem = stem.slice(0, Math.max(3, Math.min(stem.length, 5)));
          const lw = letters(w), stem2 = lw.slice(0, Math.max(3, Math.min(lw.length, 5)));
          if (!lex.includes(stem) && !lex.includes(stem2)) add(r._row, soz, UZ.misol, XATO, "misol_sozsiz", `Misol gapda «${w}» so‘zi qatnashmagan`, short(exs, 140), "So‘z qatnashgan misol keltirilsin");
          if (x.ex >= 75) {
            if ((x.kind === "izoh" || x.kind === "o'xshash") && x.sense && x.exSense !== x.sense && x.ex - x.exIn >= 15) {
              const s2 = ent.s.find(s => s.n === x.exSense);
              add(r._row, soz, UZ.misol, XATO, "misol_boshqa", `Misol gap boshqa ma’noga tegishli: izoh ${x.sense}-ma’no, misol esa lug‘atda ${x.exSense}-ma’no ostida berilgan`,
                `${x.exSense}-ma’no: ${short(s2.g, 150)}`, `${x.sense}-ma’noning o‘z misoli olinsin`);
            }
          } else {
            const hasSrc = /[A-ZА-Я]\.\s?[A-ZА-Я][a-zʻ'‘’]+|[“"«][^”"»]{3,}[”"»]\s*\.?\s*$|Maqol|Gazetadan|OʻTA|O‘TA/.test(exs);
            if (!hasSrc) add(r._row, soz, UZ.misol, KORIB, "misol_manbasiz", "Misol gap lug‘atda topilmadi va manbasi (muallif/asar) ko‘rsatilmagan", "", "Misol manbasi yozilsin yoki lug‘atdagi misol olinsin");
          }
          const key = lex.slice(0, 80);
          if (key.length >= 20) { if (!seenEx.has(key)) seenEx.set(key, []); seenEx.get(key).push([r._row, soz]); }
        }
      });

      const missingS = ent.s.filter(s => !covered.has(s.n));
      if (inList || !aset.size) {
        for (const s of missingS) add(grp[0]._row, w, UZ.izoh, XATO, "mano_yoq", `«${used}»: lug‘atdagi ${s.n}-ma’no uchun sinset tuzilmagan (lug‘atda ${nsen} ta ma’no, talabada ${grp.length} ta qator)`,
          `${s.n}-ma’no: ${short(s.g, 200)}`, "Shu ma’no uchun alohida qator qo‘shilsin");
      }
      for (const [n, rs] of covered) if (rs.length > 1) add(rs[1]._row, cellStr(rs[1].soz), UZ.izoh, OGOH, "mano_takror", `Lug‘atdagi ${n}-ma’no ikki marta sinset qilingan (qatorlar: ${rs.map(x => x._row).join(", ")})`, "", "Takror qator birlashtirilsin");
      if (ent.m && ent.m.length) add(grp[0]._row, w, "", KORIB, "ocr", `OCR bazada «${used}» maqolasining ${ent.m.join(", ")}-raqamli ma’nosi aniqlanmadi — ma’nolar soni qo‘lda (PDF bo‘yicha) tekshirilsin`);
      if (inList && !wrongEntry) coveredAssigned += ent.s.length - missingS.length;

      const nums = grp.map(r => r._n);
      if (grp.length > 1 && nums.some(n => n == null)) add(grp[0]._row, w, UZ.soz, OGOH, "raqam", "Ko‘p ma’noli so‘z qatorlari raqamlanmagan (so‘z_01, so‘z_02 …)");
      else if (grp.length > 1 && nums.slice().sort((a, b) => a - b).join() !== grp.map((_, i) => i + 1).join()) add(grp[0]._row, w, UZ.soz, OGOH, "raqam", `Ma’no raqamlari ketma-ket emas: ${nums.join(", ")}`);

      let expect = null;
      if (used.endsWith("moq")) expect = "Fe'l"; else if (ent.l.length === 1) expect = ent.l[0];
      grp.forEach((r, gi) => {
        const x = m[gi], pos = normWord(r.turkum), soz = cellStr(r.soz);
        if (isEmpty(r.turkum)) add(r._row, soz, UZ.turkum, XATO, "turkum_bosh", "Turkum ko‘rsatilmagan");
        else if (!(pos in POS_OK)) add(r._row, soz, UZ.turkum, OGOH, "turkum_nostd", `Turkum nomi standart emas: «${r.turkum}»`, "", "Ot / Sifat / Fe'l / Ravish / Son / Olmosh / Taqlid so'z …");
        else if (expect && x.kind !== "birikma" && POS_OK[pos] !== expect && !(ent.l.length === 1 && ent.s.length > 1))
          add(r._row, soz, UZ.turkum, OGOH, "turkum_farq", `Turkum «${r.turkum}» deb berilgan, lug‘at belgisi bo‘yicha: ${expect}`, `Lug‘atdagi grammatik belgi: ${ent.l.join(", ") || "-moq shakli"}`, "Turkum qayta ko‘rib chiqilsin");
      });
      const st = (!missingS.length && grp.length === nsen) ? "To‘liq" : (missingS.length ? "Ma’no yetishmaydi" : "Ortiqcha qator bor");
      wordTable.push([w, inList ? "+" : "–", used, nsen, grp.length, missingS.map(s => s.n).join(", ") || "—", grp.length > covered.size ? grp.length - covered.size : 0,
        !inList && aset.size ? "Ro‘yxatda yo‘q" : (wrongEntry ? "Boshqa maqola ishlangan" : st)]);
    }
    for (const w of missing) {
      const ent = entry(w);
      wordTable.push([w, "+", w, ent ? ent.s.length : "", 0, ent ? ent.s.map(s => s.n).join(", ") : "", 0, "ISHLANMAGAN"]);
    }
    for (const lst of seenEx.values()) if (lst.length > 1) add(lst[1][0], lst[1][1], UZ.misol, XATO, "misol_takror", `Bir xil misol gap bir necha qatorda ishlatilgan (qatorlar: ${lst.map(a => a[0]).join(", ")})`, "", "Har bir ma’noga o‘z misoli berilsin");

    // munosabat ustunlari
    const rel = ["sinonim", "antonim", "giperonim", "giponim", "xolonim", "meronim"];
    rows.forEach((r, i) => {
      const w = r._w || "", soz = cellStr(r.soz), ent = rowEnt[i];
      for (const k of REQUIRED) {
        if (k in hdr && !["soz", "izoh", "misol", "turkum"].includes(k) && (r[k] == null || String(r[k]).trim() === ""))
          add(r._row, soz, UZ[k], OGOH, "katak_bosh", `«${UZ[k]}» katagi butunlay bo‘sh`, "", "Topilmasa «-» yoki «qat’iy yo‘q» deb yozilsin");
      }
      const it = {};
      for (const k of rel) it[k] = splitItems(r[k]).map(normWord);
      if (it.sinonim.includes(w)) add(r._row, soz, UZ.sinonim, XATO, "sin_ozi", "Sinonim sifatida so‘zning o‘zi yozilgan");
      let b = inter(it.sinonim, it.giperonim);
      if (b.length) add(r._row, soz, UZ.giperonim, XATO, "sin_gip", `Bir xil birlik ham sinonim, ham giperonim: ${b.join(", ")}`, "", "Sinonim o‘rnini bosadi, giperonim kengroq tushuncha — bittasi qoldirilsin");
      b = inter(it.sinonim, it.giponim);
      if (b.length) add(r._row, soz, UZ.giponim, XATO, "sin_gip", `Bir xil birlik ham sinonim, ham giponim: ${b.join(", ")}`);
      b = inter(it.sinonim, it.antonim);
      if (b.length) add(r._row, soz, UZ.antonim, XATO, "sin_gip", `Bir xil birlik ham sinonim, ham antonim: ${b.join(", ")}`);
      for (const [a, c] of [["giponim", "xolonim"], ["giponim", "meronim"], ["giperonim", "xolonim"], ["xolonim", "meronim"]]) {
        b = inter(it[a], it[c]);
        if (b.length) add(r._row, soz, UZ[c], XATO, "rel_takror", `«${UZ[a]}» va «${UZ[c]}» ustunlarida bir xil birlik: ${b.join(", ")}`, "", "Tur–jins (giponim) va butun–qism (xolonim/meronim) munosabatlari ajratilsin");
      }
      const pos = POS_OK[normWord(r.turkum)] || "";
      if ((pos === "Sifat" || pos === "Ravish") && it.giponim.length) {
        const lw = letters(w), key = lw.slice(0, Math.max(4, lw.length - 1));
        const colloc = it.giponim.filter(x => letters(x).includes(key) && x.includes(" "));
        if (colloc.length >= Math.max(1, Math.floor(it.giponim.length / 2)))
          add(r._row, soz, UZ.giponim, KORIB, "gpn_birikma", `Giponim o‘rnida so‘z birikmalari berilgan: ${short(r.giponim, 90)}`, "", `«${w} + ot» birikmasi giponim emas — bu qo‘llanish misoli. Tur bo‘lmasa «-» qo‘yilsin`, true);
      }
      if (ent) {
        const body = letters(ent.s.map(s => s.t).join(" "));
        const inBody = x => { const lx = letters(x); const l2 = lx.endsWith("moq") && lx.length > 6 ? lx.slice(0, -3) : lx; return lx.length >= 3 && (body.includes(lx) || body.includes(l2)); };
        if (it.sinonim.length) {
          const ok = it.sinonim.filter(inBody), no = it.sinonim.filter(x => !inBody(x));
          notes[i].sin = [ok.length ? "✓ " + ok.join(", ") : "", no.length ? "✗ " + no.join(", ") : ""].filter(Boolean).join("; ");
        }
        if (it.antonim.length && !it.antonim.some(inBody))
          add(r._row, soz, UZ.antonim, KORIB, "ant_manbasiz", `Antonim «${short(r.antonim, 80)}» izohli lug‘at maqolasida (zid.) ko‘rsatilmagan`, "", "Qat’iy leksik antonim bo‘lmasa «-» qo‘yilsin", true);
      }
    });

    let expected = 0;
    for (const w of assigned) { const e = entry(w); if (e) expected += e.s.length; }
    const xatoRows = new Set(issues.filter(x => x.daraja === XATO && typeof x.row === "number").map(x => x.row));
    const stats = {
      assigned: assigned.length, done: assigned.length ? assigned.filter(w => groups.has(w)).length : groups.size,
      missingWords: missing, extraWords: extra, rows: rows.length, expected: assigned.length ? expected : null,
      covered: coveredAssigned, cleanRows: rows.filter(r => !xatoRows.has(r._row)).length,
    };

    const aiReq = rows.map((r, i) => {
      const ent = rowEnt[i], n = notes[i], s = ent && n.senseN ? ent.s.find(s => s.n === n.senseN) : null;
      const tal = {};
      for (const k of ["izoh", "misol", "turkum", "soha", "sinonim", "antonim", "giperonim", "giponim", "xolonim", "meronim"]) tal[k] = r[k] == null ? null : cellStr(r[k]);
      return { qator: r._row, soz: cellStr(r.soz), lugat_maqolasi: n.used, lugat_mano_raqami: n.senseN, lugat_izohi: s ? s.g : null,
        lugat_misollari: s ? short(s.e, 500) : null, lugatdagi_barcha_manolar: ent ? ent.s.map(x => `${x.n}) ${short(x.g, 140)}`) : [],
        lugat_grammatik_belgisi: ent ? ent.l : [], talaba: tal, _skip: n.skip };
    });
    return { issues, notes, wordTable, stats, aiReq };
  }

  // ---------------------------------------------------------------- AI lingvist
  const AI_COLS = ["izoh", "misol", "turkum", "sinonim", "antonim", "giperonim", "giponim", "xolonim", "meronim"];
  const AI_PROMPT = `Sen o‘zbek tili leksikologiyasi va WordNet tuzish bo‘yicha tajribali tilshunossan. Talaba tuzgan sinsetlarni MAZMUNAN baholaysan. Tuzilma, ma’nolar soni va izoh/misolning lug‘atga mosligini alohida dastur tekshirgan — ularni qayta tekshirma.

ASOSIY TAMOYIL. Izohli lug‘at — tayanch, lekin yagona mezon emas. Talaba yozgan birlik lug‘at maqolasida bo‘lmasa ham, tilda to‘g‘ri bo‘lsa — «to‘g‘ri» deb baholaysan. Noto‘g‘ri yoki sun’iy bo‘lsa, sababini bir qisqa gap bilan aytasan va to‘g‘ri variantni tavsiya qilasan (to‘g‘ri variant bo‘lmasa tavsiya: "-"). Har bir baho aynan shu ma’no (lugat_mano_raqami) uchun beriladi.

MEZONLAR
- turkum: izoh shakli va misoldagi vazifasiga qarab. -moq shaklisiz so‘z fe’l bo‘la olmaydi («bovar» emas, «bovar qilmoq» fe’l). -ki, -li, -siz, -iy yasalmalari odatda sifat.
- sinonim: shu ma’noda gapda o‘rnini bosa oladimi? Kengroq tushuncha sinonim emas (giperonim). So‘zning o‘zi, fonetik varianti yoki izohning tasviriy takrori sinonim emas.
- antonim: faqat qat’iy leksik qarama-qarshilik; kontekstual zidlik — qisman. Katak bo‘sh, lekin tilda aniq antonim bor bo‘lsa (paranjisiz ↔ paranjili) — tavsiya qil.
- giperonim: «X — Y ning bir turi» sinovi; giperonim SHU TURKUMDAGI kengroq so‘z bo‘lishi kerak. Sifat, ravish, olmosh, taqlid va yordamchi so‘zlarda giperonim/giponim bo‘lmaydi (ot bilan tavsiflash — noto‘g‘ri). Fe’l giperonimi — fe’l.
- giponim: torroq tur. «So‘z + ot» erkin birikmasi (shaxsiy mulk, tig‘li pichoq) giponim emas. Otlarda barqaror tur nomlari (sport jamoasi, unli fonema) qabul qilinadi; egalik birikmalari (oila ahilligi) — qisman.
- xolonim/meronim: butun–qism, to‘plam–a’zo, modda–tarkib. Sinf yoki soha (giperonim takrori) xolonim emas. Narsaning idishi, sharti yoki misoli meronim emas.
- izoh, misol: faqat jiddiy mazmuniy nuqson bo‘lsa yoz (masalan, izoh o‘rniga etimologiya yozilgan); aks holda bu ikki ustunni yozma.

JAVOB SHAKLI — faqat bitta JSON obyekt, boshqa matn yo‘q:
{"<qator raqami>": {"<ustun>": "T" | ["Q", "sabab", "tavsiya"] | ["N", "sabab", "tavsiya"] | ["B", "sabab", "tavsiya"], ...}, ...}
- "T" — to‘g‘ri. "Q" — qisman to‘g‘ri. "N" — noto‘g‘ri. "B" — katak bo‘sh, lekin to‘ldirish mumkin (tavsiya ber).
- Ustun nomlari: turkum, sinonim, antonim, giperonim, giponim, xolonim, meronim (kerak bo‘lsa izoh, misol).
- To‘ldirilgan har bir turkum va munosabat katagiga baho ber. Bo‘sh ("-" yoki null) katak to‘g‘ri bo‘sh qoldirilgan bo‘lsa, u ustunni yozma.
- Amin bo‘lmasang, massivga to‘rtinchi element sifatida "past" qo‘sh: ["Q", "sabab", "tavsiya", "past"]. O‘ylab chiqarma.
- Sabab 12 so‘zdan oshmasin. Javob o‘zbek tilida (lotin).

QATORLAR:
`;

  function aiBatches(aiReq, size) {
    const todo = aiReq.filter(q => !q._skip).map(q => { const c = Object.assign({}, q); delete c._skip; return c; });
    const out = [];
    for (let i = 0; i < todo.length; i += size) out.push(todo.slice(i, i + size));
    return out;
  }
  function aiPrompt(batch) { return AI_PROMPT + JSON.stringify(batch); }
  const BAHO = { T: "togri", Q: "qisman", N: "notogri", B: "tavsiya", togri: "togri", qisman: "qisman", notogri: "notogri", tavsiya: "tavsiya" };
  /** AI javobini (ixcham yoki to'liq shakl) yagona shaklga keltiradi va talaba kataklari bilan tekshiradi. */
  function aiNormalize(raw, aiReq) {
    const byRow = {};
    for (const q of aiReq) byRow[String(q.qator)] = q;
    const src = raw && raw.qatorlar && typeof raw.qatorlar === "object" ? raw.qatorlar : raw;
    const out = {};
    if (!src || typeof src !== "object") return out;
    for (const k of Object.keys(src)) {
      const q = byRow[String(k).trim()], v = src[k];
      if (!q || !v || typeof v !== "object") continue;
      const res = {};
      if (typeof v.holat === "string") res.holat = v.holat;
      for (const col of AI_COLS) {
        let x = v[col];
        if (x == null) continue;
        let d = null;
        if (typeof x === "string") d = { baho: BAHO[x.trim()] || BAHO[x.trim().toUpperCase()] };
        else if (Array.isArray(x)) d = { baho: BAHO[String(x[0]).trim()] || BAHO[String(x[0]).trim().toUpperCase()], izoh: x[1], tavsiya: x[2], ishonch: x[3] };
        else if (typeof x === "object") d = { baho: BAHO[String(x.baho).trim()], izoh: x.izoh, tavsiya: x.tavsiya, ishonch: x.ishonch };
        if (!d || !d.baho) continue;
        const empty = isEmpty(q.talaba[col]);
        if (empty && d.baho !== "tavsiya") continue;
        if (!empty && d.baho === "tavsiya") continue;
        const rec = { baho: d.baho };
        if (d.izoh && String(d.izoh).trim()) rec.izoh = String(d.izoh).trim();
        if (d.tavsiya && String(d.tavsiya).trim()) rec.tavsiya = String(d.tavsiya).trim();
        if (String(d.ishonch || "").trim() === "past") rec.ishonch = "past";
        res[col] = rec;
      }
      if (Object.keys(res).length) out[String(q.qator)] = res;
    }
    return out;
  }
  const REL4 = ["giperonim", "giponim", "xolonim", "meronim"];
  /** opts.otEmasChiqar: ot bo'lmagan so'zlarda giperonim/giponim/xolonim/meronim kataklari ballga kirmaydi */
  function aiCounts(ai, rows, opts) {
    const c = { togri: 0, qisman: 0, notogri: 0, tavsiya: 0, past: 0, chiqarilgan: 0, sT: 0, sQ: 0, sN: 0 };
    if (!ai) return c;
    const pos = {};
    for (const r of rows) pos[String(r._row)] = POS_OK[normWord(r.turkum)] || "";
    for (const k in ai) for (const col of AI_COLS) {
      const v = ai[k][col];
      if (!v) continue;
      c[v.baho]++;
      if (v.ishonch === "past") c.past++;
      if (v.baho === "tavsiya") continue;
      if (opts && opts.otEmasChiqar && REL4.includes(col) && pos[k] !== "Ot") { c.chiqarilgan++; continue; }
      if (v.baho === "togri") c.sT++; else if (v.baho === "qisman") c.sQ++; else c.sN++;
    }
    return c;
  }

  // ---------------------------------------------------------------- ball
  const DEFAULTS = { maxBall: 100, wQamrov: 40, wSifat: 20, wAI: 40, otEmasChiqar: true };
  function grade(stats, ai, rows, set) {
    set = Object.assign({}, DEFAULTS, set || {});
    const qamrov = stats.expected ? Math.min(1, stats.covered / stats.expected) : null;
    const sifat = stats.rows ? stats.cleanRows / stats.rows : 0;
    const c = aiCounts(ai, rows, set);
    const n = c.sT + c.sQ + c.sN;
    const aiSc = n ? (c.sT + 0.5 * c.sQ) / n : null;
    let num = 0, den = 0;
    if (qamrov != null) { num += set.wQamrov * qamrov; den += set.wQamrov; }
    num += set.wSifat * sifat; den += set.wSifat;
    if (aiSc != null) { num += set.wAI * aiSc; den += set.wAI; }
    const ball = den ? Math.round(set.maxBall * num / den * 10) / 10 : 0;
    return { ball, max: set.maxBall, qamrov, sifat, ai: aiSc, aiCounts: c, aiBor: aiSc != null };
  }

  // ---------------------------------------------------------------- umumiy feedback (qoidaga asoslangan)
  function ismi(full) {
    const p = String(full || "").split(/\s+/);
    const n = p[1] || p[0] || "";
    return n ? n.charAt(0).toUpperCase() + n.slice(1).toLowerCase() : "";
  }
  function feedback(name, res, g, ai) {
    const s = res.stats, by = {};
    for (const x of res.issues) { (by[x.kod] = by[x.kod] || []).push(x); }
    const words = (kod, n) => [...new Set((by[kod] || []).map(x => String(x.soz).replace(/_\d+$/, "")))].slice(0, n || 3).join(", ");
    const out = [];
    const nm = ismi(name);
    let head = (nm ? nm + ", " : "") + (s.assigned ? `${s.assigned} ta so‘zdan ${s.done} tasi ishlangan` : `${s.done} ta so‘z ishlangan`);
    if (s.expected) head += `; lug‘atdagi ${s.expected} ta ma’nodan ${s.covered} tasi uchun sinset to‘g‘ri tuzilgan`;
    out.push(head + ".");
    const pct = s.rows ? Math.round(100 * s.cleanRows / s.rows) : 0;
    if (pct >= 70) out.push(`Yaxshi tomoni: ${s.rows} qatorning ${pct}%ida izoh va misol lug‘atga mos, tuzilmaviy xato yo‘q.`);
    const k = [];
    if (by.soz_yoq) k.push(`berilgan so‘z ishlanmagan (${words("soz_yoq")})`);
    if (by.soz_ortiqcha) k.push(`ro‘yxatda yo‘q so‘z ishlangan (${words("soz_ortiqcha")})`);
    if (by.boshqa_maqola) k.push(`boshqa lug‘at maqolasi ishlangan (${words("boshqa_maqola")})`);
    if (by.mano_yoq) k.push(`${by.mano_yoq.length} ta ma’no tashlab ketilgan (${words("mano_yoq")})`);
    if (by.birikma) k.push(`turg‘un birikma alohida sinset qilingan (${words("birikma")}) — lug‘atda nechta ma’no bo‘lsa, shuncha sinset bo‘ladi`);
    if (by.izoh_misol || by.izoh_topilmadi || by.izoh_bosh) k.push(`izoh o‘rnida ma’no izohi yo‘q (${[words("izoh_misol"), words("izoh_topilmadi"), words("izoh_bosh")].filter(Boolean).join(", ")})`);
    if (by.misol_boshqa || by.misol_takror || by.misol_sozsiz || by.misol_bosh) k.push(`misol gap ma’noga mos emas yoki takrorlangan (${[words("misol_boshqa"), words("misol_takror"), words("misol_sozsiz"), words("misol_bosh")].filter(Boolean).join(", ")})`);
    if (by.sin_gip) k.push(`sinonim bilan giperonim/giponim aralashtirilgan (${words("sin_gip", 4)})`);
    if (by.rel_takror) k.push(`tur–jins va butun–qism munosabatlari aralashgan (${words("rel_takror")})`);
    if (k.length) out.push("Asosiy kamchiliklar: " + k.slice(0, 5).map((x, i) => `${i + 1}) ${x}`).join("; ") + (k.length > 5 ? `; yana ${k.length - 5} turdagi kamchilik hisobotda ko‘rsatilgan` : "") + ".");
    else out.push("Tuzilma bo‘yicha jiddiy kamchilik topilmadi.");
    if (ai && g.aiBor) {
      const c = g.aiCounts, cols = {};
      for (const row in ai) for (const col of AI_COLS) { const v = ai[row][col]; if (v && v.baho === "notogri") cols[col] = (cols[col] || 0) + 1; }
      const top = Object.keys(cols).sort((a, b) => cols[b] - cols[a]).slice(0, 2).map(c2 => `${UZ[c2].toLowerCase()} (${cols[c2]} ta)`);
      out.push(`Mazmuniy baho (turkum va munosabatlar): ${c.togri} ta katak to‘g‘ri, ${c.qisman} tasi qisman, ${c.notogri} tasi noto‘g‘ri` + (top.length ? `; eng ko‘p xato: ${top.join(", ")}` : "") + ".");
      if ((cols.giperonim || 0) + (cols.giponim || 0) >= 10) out.push("Eslab qoling: giperonim shu turkumdagi kengroq so‘z bo‘ladi, «so‘z + ot» birikmasi esa giponim emas; sifat va ravishlarda bu ustunlar odatda «-» bo‘ladi.");
      if (c.tavsiya) out.push(`${c.tavsiya} ta bo‘sh katakni to‘ldirish mumkin (asosan antonim/sinonim) — tavsiyalar hisobotda berilgan.`);
    }
    return out.join(" ");
  }
  function feedbackPrompt(name, res, g, ai, base) {
    const worst = [];
    for (const x of res.issues) if (x.daraja === XATO && worst.length < 14) worst.push(`${x.soz}: ${short(x.xato, 110)}`);
    const aiEx = [];
    if (ai) for (const row in ai) for (const col of AI_COLS) {
      const v = ai[row][col];
      if (v && v.baho === "notogri" && aiEx.length < 10) { const q = res.aiReq.find(q => String(q.qator) === row); aiEx.push(`${q ? q.soz : row} / ${col}: «${short(q && q.talaba[col], 50)}» — ${v.izoh || ""}`); }
    }
    return `Sen o‘zbek tili o‘qituvchisining yordamchisisan. Quyidagi tekshiruv natijalari asosida talabaga 5–7 gapli umumiy feedback yoz: o‘zbek tilida (lotin), «siz» deb, samimiy va aniq. Avval nima yaxshi chiqqanini ayt, keyin 3–4 ta eng muhim kamchilikni aniq so‘zlar misolida tushuntir, oxirida keyingi safar nimaga e’tibor berishni ayt. Ball haqida gapirma. Ro‘yxat yoki sarlavha ishlatma — bitta abzas.

Talaba: ${name}
Qisqa xulosa: ${base}
Tuzilmaviy xatolar:
- ${worst.join("\n- ") || "yo‘q"}
Mazmuniy xatolar (AI lingvist):
- ${aiEx.join("\n- ") || "baholanmagan"}`;
  }

  return { XATO, OGOH, KORIB, UZ, AI_COLS, REL4, DEFAULTS, POS_OK, normWord, letters, baseWord, isEmpty, short, cellStr, partial, pscore, ratio,
    readSubmission, findStudent, check, aiBatches, aiPrompt, aiNormalize, aiCounts, grade, feedback, feedbackPrompt, ismi };
});
