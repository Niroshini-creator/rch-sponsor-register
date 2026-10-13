/* Browser port of matcher/{pay,eligibility,matching,roles,directory}.py.
 * Every table and regular expression comes from data/engine.json, generated from the Python modules, so the two
 * engines share one source of truth; tests/parity.test.js runs both on the real feed and compares the results. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Engine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  let D = null, RX = {}, STOP = new Set(), SPONSORING = new Set(), NOISE = new Set(), EUROPE = new Set();
  const rx = (r, extra) => new RegExp(r.source, (r.flags || "") + (extra || ""));

  function init(data) {
    D = data;
    RX = {};
    for (const [k, v] of Object.entries(data.regex)) RX[k] = rx(v);
    RX.regionWords = rx(data.region_words, "g");
    RX.wordG = rx(data.regex.word, "g");
    RX.numberG = rx(data.regex.number, "g");
    RX.segmentG = rx(data.regex.segment, "g");
    STOP = new Set(data.stop); SPONSORING = new Set(data.sponsoring); NOISE = new Set(data.name_noise); EUROPE = new Set(data.europe);
    D.kwRes = {}; D.titleRes = {};
    for (const [name, fam] of Object.entries(data.roles)) {
      D.kwRes[name] = fam.keywords.map(k => [k, new RegExp("(?<![a-z0-9])" + esc(k) + "(?![a-z0-9])", "i")]);
      D.titleRes[name] = new RegExp(fam.titles.map(esc).join("|"), "i");
    }
    return api;
  }
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // Python's round() rounds halves to even; JavaScript's rounds them up. Scores must agree exactly.
  function pyRound(x) {
    const r = Math.round(x);
    return Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : r;
  }
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const nums = text => { const out = []; let m; RX.numberG.lastIndex = 0;
    while ((m = RX.numberG.exec(text))) out.push([m[1], m[2]]); return out; };
  const num = s => parseFloat(s.replace(/,/g, ""));
  const isDigits = s => /^\d+$/.test(s.replace(/,/g, "").replace(/\./g, ""));

  // ---------------------------------------------------------------- pay (pay.py, jobfeed/salary.py)
  function inrAnnualRange(salary) {
    if (!salary) return null;
    const text = salary.split("₹").join(" ").split("Rs.").join(" ").split("Rs").join(" ").split("INR").join(" ");
    const lpa = /(\d[\d,]*(?:\.\d+)?)\s*(?:-|–|to)?\s*(?:(\d[\d,]*(?:\.\d+)?))?\s*(lpa|lakhs?|lacs?|l\.p\.a|crores?|cr)\b/i.exec(text);
    if (lpa) {
      const mult = lpa[3].toLowerCase().startsWith("cr") ? 1e7 : 1e5;
      const lo = num(lpa[1]) * mult, hi = lpa[2] ? num(lpa[2]) * mult : lo;
      return [Math.min(lo, hi), Math.max(lo, hi)];
    }
    const ns = nums(text).map(p => p[0]).filter(isDigits).map(num);
    if (!ns.length) return null;
    if (/\b(per|a|each)\s+month\b|\bpm\b|\/\s*month\b|\bmonthly\b/i.test(text)) {
      const m = ns.filter(n => n >= 5000 && n < 5e6).map(n => n * 12);
      return m.length ? [Math.min(...m), Math.max(...m)] : null;
    }
    const y = ns.filter(n => n >= 1e5 && n < 1e9);
    return y.length ? [Math.min(...y), Math.max(...y)] : null;
  }
  const lakhs = r => pyRound(r / 1e5 * 10) / 10;

  function annualRange(salary, country) {
    if (!salary) return null;
    const other = country === "GB" ? RX.other_currency_gb : country === "IE" ? RX.other_currency_ie : null;
    if (other && other.test(salary)) return null;
    const ns = nums(salary).filter(p => isDigits(p[0])).map(p => num(p[0]) * (p[1] ? 1000 : 1));
    if (!ns.length) return null;
    if (RX.daily.test(salary)) return null;
    const lo = a => Math.min(...a), hi = a => Math.max(...a);
    if (RX.hourly.test(salary)) {
      const r = ns.filter(n => n >= 5 && n < 200);
      return r.length ? [lo(r) * D.hours_per_year, hi(r) * D.hours_per_year] : null;
    }
    if (RX.monthly.test(salary)) {
      const m = ns.filter(n => n >= 500 && n < 50000);
      return m.length ? [lo(m) * 12, hi(m) * 12] : null;
    }
    if (RX.weekly.test(salary)) {
      const w = ns.filter(n => n >= 100 && n < 10000);
      return w.length ? [lo(w) * 52, hi(w) * 52] : null;
    }
    const years = ns.filter(n => n >= 10000 && n < 2000000);
    if (years.length) return [lo(years), hi(years)];
    if (RX.annual.test(salary)) {
      const small = ns.filter(n => n >= 1000);
      return small.length ? [lo(small), hi(small)] : null;
    }
    const rates = ns.filter(n => n >= 5 && n < 100);
    if (rates.length && rates.length === ns.length) return [lo(rates) * D.hours_per_year, hi(rates) * D.hours_per_year];
    return null;
  }

  // ---------------------------------------------------------------- eligibility (eligibility.py)
  const sponsorshipMode = c => {
    const m = c.sponsorship_mode;
    if (m === "required" || m === "preferred" || m === "not_needed") return m;
    return (c.needs_sponsorship === undefined ? true : c.needs_sponsorship) ? "required" : "not_needed";
  };
  function minFor(c, country) {
    const t = c.min_salary;
    if (t === null || typeof t !== "object") return (country === "GB" || country === "IE") ? Number(t || 0) : 0;
    if (country === "IN") return Number(t.IN || 0) * 1e5;
    return Number(t[country === "GB" || country === "IE" ? country : "EU"] || 0);
  }
  function onPayScale(job) {
    const title = job.title || "";
    if (RX.trainee.test(title)) return false;
    const clinical = RX.health.test(title) && (job.domain === "Healthcare & Clinical" || job.sector === "NHS & Healthcare");
    return Boolean(clinical || RX.teacher.test(title));
  }
  function applicable(job, c) {
    const table = D.thresholds[job.country];
    if (!table) return null;
    const labels = table.labels;
    const keys = Object.keys(labels).filter(k => k in table);
    const all = keys.map(k => ({ key: k, label: labels[k], amount: table[k] }));
    let key;
    if (job.country === "GB") key = onPayScale(job) ? "pay_scale" : (c.new_entrant || c.phd || c.shortage_role) ? "new_entrant" : "general";
    else key = RX.ie_care.test(job.title || "") ? "care" : "general";
    return [key, table[key], all];
  }
  function packageCheck(job, c, out) {
    const pay = inrAnnualRange(job.salary || "");
    const wanted = minFor(c, "IN");
    Object.assign(out, { currency: "₹", kind: "package", route: "India (no visa minimum)", floor: pyRound(wanted),
      floor_label: "Your minimum package", thresholds: [] });
    if (pay) {
      out.pay_low = pyRound(pay[0]); out.pay_high = pyRound(pay[1]);
      out.lakhs = pay[0] !== pay[1] ? `${lakhs(pay[0])} – ${lakhs(pay[1])} LPA` : `${lakhs(pay[1])} LPA`;
    }
    if (!pay) { out.status = "unstated"; out.note = "Package isn't stated. Ask the recruiter for the range before applying."; }
    else if (!wanted) { out.status = "unchecked"; out.note = "Set your minimum package in your profile to check this."; }
    else if (pay[1] >= wanted) { out.status = "meets"; out.note = `Package reaches your minimum of ${lakhs(wanted)} LPA.`; }
    else { out.status = "below"; out.note = `Package tops out at ${lakhs(pay[1])} LPA, below your minimum of ${lakhs(wanted)} LPA.`; }
    return out;
  }
  const comma = n => Math.round(n).toLocaleString("en-US");
  function evaluate(job, c) {
    const country = job.country || "";
    const out = { status: "unchecked", kind: "visa", currency: "", floor: 0, floor_label: "", pay_low: 0, pay_high: 0,
      thresholds: [], note: "", route: "", future: false };
    if (country === "IN") return packageCheck(job, c, out);
    const mode = sponsorshipMode(c);
    const info = applicable(job, c);
    const table = D.thresholds[country];
    if (info) Object.assign(out, { currency: table.currency, floor: info[1], floor_label: table.labels[info[0]], route: table.route });
    const pay = info ? annualRange(job.salary || "", country) : null;
    if (pay) { out.pay_low = pyRound(pay[0]); out.pay_high = pyRound(pay[1]); }
    if (info) out.thresholds = info[2].map(t => Object.assign({}, t, { met: Boolean(pay) && pay[1] >= t.amount }));
    if (mode === "not_needed") { out.status = "not_needed"; out.note = "You don't need sponsorship, so the visa salary minimum doesn't apply."; return out; }
    const prefix = mode === "preferred" ? "For future sponsorship: " : "";
    out.future = mode === "preferred";
    if (!info) { out.note = "No visa salary check is available for this country. Ask the employer about visa pay rules."; return out; }
    const cur = out.currency, floor = out.floor;
    if (!pay) {
      out.status = "unstated";
      out.note = `Pay isn't stated or can't be read. Check it reaches ${cur}${comma(floor)} (${out.floor_label}) before applying.`;
      return out;
    }
    const [low, high] = pay;
    let note;
    if (low >= floor) { out.status = "meets"; note = `${prefix}pay meets the ${out.floor_label[0].toLowerCase() + out.floor_label.slice(1)} (${cur}${comma(floor)}).`; }
    else if (high >= floor) { out.status = "partial"; note = `${prefix}only the top of the range reaches ${cur}${comma(floor)}. Ask which point you would start on.`; }
    else { out.status = "below"; note = `${prefix}pay is below the ${cur}${comma(floor)} minimum that applies to you (${out.floor_label}), so the role can't be sponsored at this pay.`; }
    out.note = note[0].toUpperCase() + note.slice(1) + " The occupation's going rate can be higher; confirm with the employer.";
    return out;
  }

  // ---------------------------------------------------------------- matching (matching.py)
  const stripChars = (s, chars) => { let a = 0, b = s.length; while (a < b && chars.includes(s[a])) a++; while (b > a && chars.includes(s[b - 1])) b--; return s.slice(a, b); };
  function tokens(text) {
    const out = [];
    for (const w of (text.toLowerCase().match(RX.wordG) || [])) if (!STOP.has(w)) out.push(stripChars(w, ".-&"));
    return out;
  }
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  function extractKeywords(text, limit = 30) {
    const known = [];
    for (const fam of Object.values(D.roles)) for (const kw of fam.keywords)
      if (!known.includes(kw) && new RegExp("(?<![a-z0-9])" + esc(kw) + "(?![a-z0-9])", "i").test(text)) known.push(kw);
    const counts = new Map();
    const bump = (k, n) => counts.set(k, (counts.get(k) || 0) + n);
    for (const segment of text.toLowerCase().split(RX.segmentG)) {
      const words = tokens(segment);
      for (const w of words) if (w.length > 3) bump(w, 1);
      for (let i = 0; i + 1 < words.length; i++) if (words[i].length > 2 && words[i + 1].length > 2) bump(words[i] + " " + words[i + 1], 2);
    }
    const repeated = [...counts].filter(([, v]) => v >= 3).sort((a, b) => b[1] - a[1] || cmp(a[0], b[0]));
    const chosen = known.slice();
    for (const [k] of repeated) if (!chosen.some(c => c.includes(k) || k.includes(c))) chosen.push(k);
    return chosen.slice(0, limit);
  }
  const isGraduateRole = job => Boolean(job.early_career) || RX.graduate.test(job.title || "");
  function visaDaysLeft(c, today) {
    const d = Date.parse((c.visa_expiry || "") + "T00:00:00Z");
    if (Number.isNaN(d)) return null;
    const t = today ? Date.parse(today + "T00:00:00Z") : Date.UTC(...(() => { const n = new Date(); return [n.getFullYear(), n.getMonth(), n.getDate()]; })());
    return Math.round((d - t) / 864e5);
  }
  function tracksOf(c) {
    const tracks = (c.tracks || []).slice().sort((a, b) => (a.priority ?? 9) - (b.priority ?? 9));
    if (tracks.length) return tracks;
    return [{ id: null, name: "Preferred roles", priority: 1, target_roles: c.target_roles || [], keywords: c.keywords || [], filename: "" }];
  }
  function passesFilters(job, c, opts = {}) {
    const mode = sponsorshipMode(c);
    const home = new Set((c.countries && c.countries.length) ? c.countries : ["GB"]);
    const country = job.country, sp = job.sponsorship || "";
    let abroad = false;
    if (!home.has(country)) {
      if (country === "IN" && c.open_to_india) { /* opted in */ }
      else if (EUROPE.has(country) && c.open_to_europe) abroad = true;
      else return false;
    }
    if (country !== "IN") {
      if (mode === "required" || (abroad && mode !== "not_needed")) {
        if (sp === "graduate_route") { if (c.visa_type !== "graduate") return false; }
        else if (!SPONSORING.has(sp)) return false;
      }
      if (mode === "required" && job.low_sponsorship) return false;
      if (mode === "preferred" && (opts.sponsoredOnly || c.sponsored_only) && !SPONSORING.has(sp)) return false;
    }
    if (c.graduate_only && !isGraduateRole(job)) return false;
    const sectors = c.sectors || [];
    if (sectors.length && !sectors.includes(job.sector)) return false;
    return true;
  }
  function titleScore(targets, title) {
    const tt = new Set(tokens(title));
    let best = 0, bestTarget = "";
    for (const target of targets) {
      const wanted = new Set(tokens(target));
      if (!wanted.size) continue;
      let hit = 0; for (const w of wanted) if (tt.has(w)) hit++;
      let ratio = hit / wanted.size;
      if (title.toLowerCase().includes(target.toLowerCase())) ratio = 1;
      if (ratio > best) { best = ratio; bestTarget = target; }
    }
    return [best, bestTarget];
  }
  function score(job, c, pay, track, today) {
    const targets = track.target_roles || [];
    const keywords = (track.keywords || []).map(k => k.toLowerCase()).slice(0, 30);
    const parts = [];
    if (targets.length) {
      const [ratio, matched] = titleScore(targets, job.title || "");
      const pts = pyRound(40 * ratio);
      parts.push({ label: "Job title", points: pts, max: 40, detail: pts ? `matches “${matched}”` : "no target role in the title" });
    } else parts.push({ label: "Job title", points: 20, max: 40, detail: "no target roles set" });

    if (keywords.length) {
      const hay = `${job.title || ""} ${job.description || ""} ${job.role || ""}`.toLowerCase();
      const hits = keywords.filter(k => hay.includes(k));
      const pts = pyRound(25 * Math.min(1, hits.length / Math.max(3, Math.min(keywords.length, 10))));
      parts.push({ label: "CV keywords", points: pts, max: 25, detail: hits.length ? hits.slice(0, 6).join(", ") : "none found in the advert text" });
    } else parts.push({ label: "CV keywords", points: 12, max: 25, detail: "no CV keywords yet" });

    const places = (c.locations || []).map(p => p.toLowerCase());
    const where = `${job.location || ""} ${job.region || ""}`.toLowerCase();
    const home = (c.countries && c.countries.length) ? c.countries : ["GB"];
    const away = !home.includes(job.country);
    if (!places.length || away) parts.push({ label: "Location", points: 15, max: 15, detail: away ? "in a country you're open to" : "no place preference set" });
    else if (places.some(p => where.includes(p)) || (where.includes("remote") && places.includes("remote"))) parts.push({ label: "Location", points: 15, max: 15, detail: job.location || "" });
    else parts.push({ label: "Location", points: 4, max: 15, detail: "outside your preferred places" });

    if (c.graduate_only) {
      const stated = job.early_career === "stated";
      parts.push({ label: "Graduate role", points: stated ? 10 : 7, max: 10, detail: stated ? "advert names the Graduate visa / OPT" : "early-career title" });
    } else parts.push({ label: "Level", points: 5, max: 10, detail: "no graduate preference" });

    const wanted = minFor(c, job.country || "");
    if (wanted && pay.pay_high) {
      const ok = pay.pay_high >= wanted;
      parts.push({ label: "Your minimum pay", points: ok ? 10 : 0, max: 10, detail: ok ? "pay reaches your minimum" : "pay is below your minimum" });
    } else parts.push({ label: "Your minimum pay", points: 5, max: 10, detail: wanted ? "pay not stated" : "no minimum set" });

    let total = parts.reduce((s, p) => s + p.points, 0);
    const mode = sponsorshipMode(c), sp = job.sponsorship || "";
    if (job.country !== "IN") {
      if (mode === "preferred") {
        const left = visaDaysLeft(c, today);
        const urgent = left !== null && left <= 365;
        if (SPONSORING.has(sp)) {
          const bump = urgent ? 20 : 10;
          parts.push({ label: "Employer can sponsor", points: bump, max: 0, detail: urgent ? "visa expires within a year: sponsors first" : "preferred: sponsors later" });
          total += bump;
        } else if (sp === "not_sponsored") {
          const dip = urgent ? 20 : 10;
          parts.push({ label: "Advert rules out sponsorship", points: -dip, max: 0, detail: "you can work now, but it won't help after your visa ends" });
          total -= dip;
        }
      } else if (mode === "required" && sp === "confirmed") {
        parts.push({ label: "Sponsorship offered in advert", points: 5, max: 0, detail: "" }); total += 5;
      }
      if (mode === "required") {
        if (pay.status === "below") { total -= 25; parts.push({ label: "Below visa minimum", points: -25, max: 0, detail: pay.note }); }
        else if (pay.status === "partial") { total -= 5; parts.push({ label: "Pay only partly meets visa minimum", points: -5, max: 0, detail: "" }); }
      }
    } else {
      if (pay.status === "below") { total -= 25; parts.push({ label: "Package below your minimum", points: -25, max: 0, detail: pay.note }); }
      else if (pay.status === "unstated" && pay.floor) { total -= 8; parts.push({ label: "Package not stated", points: -8, max: 0, detail: "ask before applying" }); }
    }
    return [clamp(total, 0, 100), parts];
  }
  function matchJobs(jobs, c, o = {}) {
    const minMatch = o.minMatch ?? 30, hideBelow = o.hideBelow ?? true, q = (o.query || "").toLowerCase().trim();
    const mode = sponsorshipMode(c);
    let tracks = tracksOf(c);
    if (o.trackId !== undefined && o.trackId !== null) { const f = tracks.filter(t => t.id === o.trackId); if (f.length) tracks = f; }
    const out = [];
    for (const job of jobs) {
      if (o.country && job.country !== o.country) continue;
      if (!passesFilters(job, c, { sponsoredOnly: o.sponsoredOnly })) continue;
      if (q && !`${job.title || ""} ${job.company || ""} ${job.location || ""}`.toLowerCase().includes(q)) continue;
      const pay = evaluate(job, c);
      if (hideBelow && pay.status === "below" && (pay.kind === "package" || mode === "required")) continue;
      let best = null;
      for (const track of tracks) {
        const [pts, parts] = score(job, c, pay, track, o.today);
        const rank = pts + (D.priority_bonus[track.priority ?? 9] || 0);
        if (best === null || rank > best[0]) best = [rank, pts, parts, track];
      }
      const [rank, pts, parts, track] = best;
      if (pts < minMatch) continue;
      out.push(Object.assign({}, job, { match: pts, rank, match_parts: parts, pay_check: pay,
        track: { id: track.id, name: track.name, priority: track.priority ?? 1, cv: track.filename || "" },
        sponsorship_label: D.sponsor_labels[job.sponsorship || ""] || "" }));
    }
    out.sort((a, b) => cmp(b.posted_at || "", a.posted_at || ""));
    out.sort((a, b) => b.rank - a.rank);
    return out;
  }

  // ---------------------------------------------------------------- roles (roles.py)
  const titleMatches = (role, title) => D.titleRes[role].test(title);
  function roleFit(role, text) {
    const fam = D.roles[role];
    const titles = fam.titles.filter(t => new RegExp(esc(t), "i").test(text));
    const skills = D.kwRes[role].filter(([, r]) => r.test(text)).map(([k]) => k);
    const raw = 3 * Math.min(titles.length, 3) + Math.min(skills.length, 12);
    return [Math.min(100, pyRound(100 * raw / 16)), skills, titles];
  }
  function countVacancies(jobs, c) {
    const mode = sponsorshipMode(c);
    const counts = {}; for (const r of Object.keys(D.roles)) counts[r] = 0;
    for (const job of jobs) {
      if (!passesFilters(job, c)) continue;
      if (mode === "required" && evaluate(job, c).status === "below") continue;
      for (const r of Object.keys(D.roles)) if (titleMatches(r, job.title || "")) counts[r]++;
    }
    return counts;
  }
  function suggestRoles(text, vacancies, limit = 6) {
    const out = [];
    for (const role of Object.keys(D.roles)) {
      const [fit, skills, titles] = roleFit(role, text);
      if (fit < 15) continue;
      const open = (vacancies || {})[role] || 0;
      const availability = Math.min(1, Math.log1p(open) / Math.log1p(60));
      out.push({ role, fit, skills: skills.slice(0, 8), past_titles: titles.slice(0, 3), titles: cased(D.roles[role].titles.slice(0, 6)), vacancies: open,
        score: pyRound((0.6 * fit + 0.4 * 100 * availability) * 10) / 10 });
    }
    out.sort((a, b) => b.score - a.score);
    out.forEach((item, i) => { item.suggested_priority = i < 3 && item.fit >= 25 ? i + 1 : null; });
    return out.slice(0, limit);
  }

  const ACRONYMS = new Set(["bi", "mi", "it", "hr", "qa", "sdet", "pmo", "soc", "aml", "kyc", "oss", "bss", "etl", "nlp", "ai", "seo", "ppc", "sre"]);
  const cased = list => list.map(t => t.split(/\s+/).filter(Boolean).map(w => (ACRONYMS.has(w) ? w.toUpperCase() : w.slice(0, 1).toUpperCase() + w.slice(1))).join(" "));
  function rolesFromCv(text, domain, current) {
    const name = domain.trim().toLowerCase();
    if (current.length > 1 || (current.length && current[0].trim().toLowerCase() !== name)) return [];
    const named = Object.keys(D.roles).find(r => name === r.toLowerCase() || D.roles[r].titles.includes(name));
    let chosen = null;
    if (named && roleFit(named, text)[0] >= 15) chosen = named;
    else {
      let best = null, bestFit = 0;
      for (const role of Object.keys(D.roles)) { const fit = roleFit(role, text)[0]; if (fit > bestFit) { best = role; bestFit = fit; } }
      chosen = bestFit >= 25 ? best : null;
    }
    return chosen ? cased(D.roles[chosen].titles.slice(0, 6)) : [];
  }

  // ---------------------------------------------------------------- directory (directory.py)
  function normaliseCompany(name) {
    if (!name) return "";
    let n = name.normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase().split("&").join(" and ");
    n = n.replace(/\(.*?\)/g, " ").split(".").join("");
    n = n.replace(/[^a-z0-9 ]+/g, " ");
    return n.split(/\s+/).filter(w => w && !NOISE.has(w)).join(" ");
  }
  const baseName = name => {
    const stripped = normaliseCompany(name.replace(RX.regionWords, " "));
    return stripped.length >= 3 && stripped !== "of" && stripped !== "the" ? stripped : normaliseCompany(name);
  };
  function directoryListing(rows, jobs, c, o = {}) {
    const byCompany = new Map(rows.filter(r => r.category !== "Job board" && r.category !== "Official").map(r => [r.base + "|" + r.country, r]));
    const totals = new Map(), forYou = new Map(), licensed = new Set();
    for (const job of jobs) {
      const key = job.ckey + "|" + job.country;
      if (!byCompany.has(key)) continue;
      totals.set(key, (totals.get(key) || 0) + 1);
      if (job.sponsor_register) licensed.add(key);
      if (c && passesFilters(job, c)) forYou.set(key, (forYou.get(key) || 0) + 1);
    }
    const needle = (o.q || "").toLowerCase().trim();
    const fc = {}, fk = {}, list = [];
    const all = rows.map(r => { const key = r.base + "|" + r.country;
      const { base, ...rest } = r;
      return Object.assign({}, rest, { open_total: totals.get(key) || 0, open_for_you: forYou.get(key) || 0, licensed_sponsor: licensed.has(key), _base: base }); });
    for (const r of all) {
      if (needle && !`${r.name} ${r.note || ""}`.toLowerCase().includes(needle)) continue;
      fc[r.country] = (fc[r.country] || 0) + 1; fk[r.category] = (fk[r.category] || 0) + 1;
      if ((o.country && r.country !== o.country) || (o.category && r.category !== o.category)) continue;
      list.push(r);
    }
    const mine = new Set((c && c.countries) || []);
    if (c && c.open_to_india) mine.add("IN");
    if (c && c.open_to_europe) { for (const r of list) if (EUROPE.has(r.country)) mine.add(r.country); mine.add("EU"); }
    list.sort((a, b) => (mine.has(a.country) ? 0 : 1) - (mine.has(b.country) ? 0 : 1) || b.open_for_you - a.open_for_you ||
      b.open_total - a.open_total || (a.link_type !== "page") - (b.link_type !== "page") || cmp(a.name.toLowerCase(), b.name.toLowerCase()));
    for (const r of list) delete r._base;
    return { sites: list, countries: fc, categories: fk };
  }
  function linkFor(rows, job) {
    const r = rows.find(x => x.base === job.ckey && x.country === job.country && x.category !== "Job board" && x.category !== "Official");
    return r ? r.careers_url : "";
  }

  const api = { init, pyRound, inrAnnualRange, annualRange, evaluate, sponsorshipMode, minFor, tokens, extractKeywords, passesFilters,
    score, matchJobs, countVacancies, suggestRoles, roleFit, titleMatches, rolesFromCv, normaliseCompany, baseName, directoryListing, linkFor,
    visaDaysLeft, tracksOf, get data() { return D; } };
  return api;
});
