/* Browser port of candidateboard/{match,checks}.py and the pay rules in jobfeed/salary.py. It scores a job from the shared
 * feed against a candidate profile, so the board can show roles newer than the daily build. tests/test_match_js.py runs both
 * engines on the real feed and compares every label and score. Needs CandidateIntake (intake.js) initialised first. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./intake.js"));
  else root.CandidateMatch = factory(root.CandidateIntake);
})(typeof self !== "undefined" ? self : this, function (I) {
  "use strict";
  const pyRound = x => { const r = Math.round(x); return Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : r; };

  // ------------------------------------------------------------------ checks.py
  const CLEARANCE_ORDER = ["none", "dbs", "basic", "unspecified", "nppv", "ctc", "sc", "dv"];
  const BLOCKING = new Set(["unspecified", "nppv", "ctc", "sc", "dv"]);
  const LEVELS = [
    ["dv", /\bDV\b(?=[\s/,&()-]{0,4}(?:clear\w*|level|vetting|check|cleared))|\bdv\s+(?:clearance|cleared|vetting)\b|\bdeveloped vetting\b|\bactive DV\b|(?<=\/)dv\s+clearance/],
    ["sc", /\bSC\b(?=[\s/,&()-]{0,4}(?:clear\w*|level|vetting|check|cleared|eligib\w*))|\bsc\s+(?:clearance|cleared|vetting)\b|\bactive SC\b|\bsecurity check \(SC\)|\bSC[- ]cleared\b|\b(?:eligible|able|willing)\s+(?:to|for)\s+(?:obtain|hold|gain|get|achieve|undergo)?\s*(?:an?\s+)?SC\b/],
    ["ctc", /\bCTC\b(?=[\s/,&()-]{0,4}(?:clear\w*|level|check))|\bcounter[- ]terroris[tm] check\b/i],
    ["nppv", /\bNPPV\s?\d?\b/i],
    ["unspecified", /\b(?:security\s+clear(?:ance|ed)|security[- ]vetted|national security vetting|\bvetting\b)/i],
    ["basic", /\b(?:BPSS|baseline personnel security|baseline (?:security )?(?:check|standard)|basic (?:security )?check)\b/i],
    ["dbs", /\b(?:DBS|disclosure and barring|criminal record check|enhanced (?:dbs|disclosure))\b/i],
  ];
  const OBTAIN = /\b(?:eligible|able|willing|prepared|ability|capable|can|must be able|undergo|obtain|gain|achieve|working towards|process of)\b/i;
  const CLEAR_LABELS = { dv: "DV clearance", sc: "SC clearance", ctc: "CTC clearance", nppv: "NPPV police vetting", unspecified: "Security clearance / vetting", basic: "Basic check (BPSS)", dbs: "DBS check" };

  function sentence(text, pos, limit = 200) {
    let start = 0;
    for (const c of ".;!?\n") start = Math.max(start, text.lastIndexOf(c, pos - 1) + 1);
    // lastIndexOf(c, -1) would search from 0; guard pos == 0
    if (pos === 0) start = 0;
    const ends = [...".;!?\n"].map(c => text.indexOf(c, pos)).filter(i => i !== -1);
    const end = ends.length ? Math.min(...ends) + 1 : text.length;
    const s = text.slice(start, end).split(/\s+/).filter(Boolean).join(" ");
    return s.length <= limit ? s : s.slice(0, limit).replace(/\s+\S*$/, "") + "…";
  }
  function clearance(text, held) {
    const found = {};
    for (const [level, rx] of LEVELS) { const m = rx.exec(text); if (m) found[level] = sentence(text, m.index); }
    const levels = Object.keys(found);
    if (!levels.length) return { level: "none", stance: "", label: "No clearance mentioned", quote: "", blocks: false };
    const level = levels.reduce((a, b) => (CLEARANCE_ORDER.indexOf(b) > CLEARANCE_ORDER.indexOf(a) ? b : a));
    const quote = found[level], stance = OBTAIN.test(quote) ? "obtain" : "required";
    const heldIdx = CLEARANCE_ORDER.includes(held) ? CLEARANCE_ORDER.indexOf(held) : 0;
    const blocks = BLOCKING.has(level) && CLEARANCE_ORDER.indexOf(level) > heldIdx;
    const label = BLOCKING.has(level) ? `${CLEAR_LABELS[level]} ${stance === "obtain" ? "(must be eligible to obtain)" : "required"}` : `${CLEAR_LABELS[level]} (standard, no clearance needed)`;
    return { level, stance, label, quote, blocks: Boolean(blocks) };
  }
  const LICENCE = /\b(?:full |valid |clean |current )?(?:uk |united kingdom |european )?driving licen[cs]e\b|\bdrive(?:r)?'?s? licen[cs]e\b|\bown (?:vehicle|transport|car)\b|\bable to drive\b/i;
  const DESIRABLE = /\b(?:desirable|preferred|advantageous|an advantage|beneficial|ideally|nice to have|would be useful)\b/i;
  function drivingLicence(text, has) {
    const m = LICENCE.exec(text);
    if (!m) return { need: "", quote: "", status: "" };
    const quote = sentence(text, m.index);
    return { need: DESIRABLE.test(quote) ? "desirable" : "required", quote, status: has == null ? "unknown" : has ? "ok" : "missing" };
  }
  const REMOTE = /\b(?:fully remote|100% remote|remote[- ]first|remote working|work(?:ing)? (?:from home|remotely)|home[- ]based|remote)\b/i;
  const HYBRID = /\bhybrid\b|\b\d\s*days? (?:a|per|in the) (?:week|office)\b/i;
  const workMode = (text, location) => { const b = `${location || ""} ${text}`; return HYBRID.test(b) ? "hybrid" : REMOTE.test(b) ? "remote" : ""; };

  const NATIONALS = "uae|emirati|saudi|qatari|kuwaiti|omani|bahraini";
  const NATIONALS_ONLY = new RegExp(`\\(\\s*(?:${NATIONALS})(?:\\s+nationals?)?\\s*\\)|\\b(?:${NATIONALS})\\s+(?:nationals?|citizens?)\\s+(?:only|required)\\b|\\b(?:${NATIONALS})\\s+only\\b|\\bonly\\s+(?:open|available)\\s+to\\s+(?:${NATIONALS})|\\b(?:nationals?|citizens?)\\s+only\\b`, "i");
  function nationalityRestriction(text) { const m = NATIONALS_ONLY.exec(text); return { restricted: Boolean(m), quote: m ? sentence(text, m.index) : "" }; }

  // ------------------------------------------------------------------ salary.py
  const UK_GENERAL = 41700, UK_REDUCED = 33400, UK_PAY_SCALE = 25000, IE_GENERAL = 36605, IE_CARE = 32691, HOURS = 37.5 * 52;
  const OTHER_CUR = { GB: /[$€]|\b(eur|usd)\b/i, IE: /[$£]|\b(gbp|usd)\b/i };
  const HOURLY = /\b(per|an|a|each)\s+hour\b|\bhourly\b|\bp\/?h\b|\/\s*h(ou)?r\b/i, MONTHLY = /\b(per|a|each)\s+month\b|\bmonthly\b|\bpcm\b|\/\s*month\b/i;
  const WEEKLY = /\b(per|a|each)\s+week\b|\bweekly\b|\/\s*week\b/i, DAILY = /\b(per|a|each)\s+day\b|\bdaily\b|\/\s*day\b|\bday rate\b/i;
  const ANNUAL = /\b(per|a|each)\s+(annum|year)\b|\bannual(ly)?\b|\bp\.?a\.?\b|\byearly\b/i;
  const HEALTH = /\b(nurse|nursing sister|charge nurse|midwi(fe|ves|fery)|health visitor|paramedic|doctor|physician|surgeon|consultant|registrar|\bgp\b|general practitioner|dentist|dental (officer|surgeon)|pharmacist|radiographer|sonographer|physiotherapist|physio\b|occupational therapist|speech (and|&) language therapist|dietitian|podiatrist|orthoptist|optometrist|audiologist|biomedical scientist|clinical scientist|(clinical|counselling) psychologist|psychotherapist|operating department practitioner)/i;
  const TEACHER = /\b(teacher|head of (department|year|faculty)|senco|headteacher|head teacher)\b/i;
  const TRAINEE = /\b(trainee|student|assistant|support worker|apprentice|hca|dental nurse|nursery nurse|nursing associate)\b/i;
  const IE_CARE_RE = /\b(healthcare assistant|health care assistant|care assistant|home carer|care worker)\b/i;
  const CURRENCY = { GB: "£", IE: "€" };

  function annualRange(salary, country) {
    if (!salary || (OTHER_CUR[country] && OTHER_CUR[country].test(salary))) return null;
    const numbers = [];
    for (const m of salary.matchAll(/(\d[\d,]*(?:\.\d+)?)\s*(k\b)?/gi)) {
      if (/^\d+$/.test(m[1].replace(/,/g, "").replace(/\./g, ""))) numbers.push(parseFloat(m[1].replace(/,/g, "")) * (m[2] ? 1000 : 1));
    }
    if (!numbers.length || DAILY.test(salary)) return null;
    const mm = a => [Math.min(...a), Math.max(...a)];
    if (HOURLY.test(salary)) { const r = numbers.filter(n => n >= 5 && n < 200); return r.length ? mm(r).map(v => v * HOURS) : null; }
    if (MONTHLY.test(salary)) { const r = numbers.filter(n => n >= 500 && n < 50000); return r.length ? mm(r).map(v => v * 12) : null; }
    if (WEEKLY.test(salary)) { const r = numbers.filter(n => n >= 100 && n < 10000); return r.length ? mm(r).map(v => v * 52) : null; }
    const years = numbers.filter(n => n >= 10000 && n < 2000000);
    if (years.length) return mm(years);
    if (ANNUAL.test(salary)) { const r = numbers.filter(n => n >= 1000); return r.length ? mm(r) : null; }
    const rates = numbers.filter(n => n >= 5 && n < 100);
    return rates.length && rates.length === numbers.length ? mm(rates).map(v => v * HOURS) : null;
  }
  function thresholds(job) {
    if (job.country === "GB") {
      const clinical = HEALTH.test(job.title) && (job.domain === "Healthcare & Clinical" || job.sector === "NHS & Healthcare");
      if ((clinical || TEACHER.test(job.title)) && !TRAINEE.test(job.title)) return [UK_PAY_SCALE, UK_PAY_SCALE];
      return [UK_GENERAL, UK_REDUCED];
    }
    if (job.country === "IE") return IE_CARE_RE.test(job.title) ? [IE_CARE, IE_CARE] : [IE_GENERAL, IE_GENERAL];
    return null;
  }
  const comma = n => Math.round(n).toLocaleString("en-US");

  // ------------------------------------------------------------------ match.py
  const TIER_FACTOR = { 1: 1.0, 2: 0.94, 3: 0.86 };
  const TITLE_LITERAL = 50, TITLE_FAMILY = 44, TITLE_PARTIAL = 30, TITLE_OTHER = 32, SKILL_MAX = 40, SKILL_EXTRACT_MAX = 22, SKILLS_FOR_FULL = 5, EXTRACT_CHARS = 600;
  const SPONSORSHIP = {
    confirmed: ["Sponsorship offered", 0, true], possible: ["Sponsorship may be available", 1, true], licensed_sponsor: ["Licensed sponsor (advert silent)", 2, true],
    employer_visa: ["Employer provides visa", 2, true], graduate_route: ["Not sponsoring, open to Graduate visa holders", 4, false],
    stamp_1g: ["No sponsorship evidence (Ireland: open to Stamp 1G holders only)", 5, false], unverified: ["Employer not on sponsor register", 5, false], agency: ["Agency advert, end employer unknown", 5, false], not_sponsored: ["Sponsorship not offered", 6, false],
  };
  const RIGHTS = { us_opt: "US", ie_stamp_1g: "IE" };   // visa.work_rights key -> country where it lets the holder work without a sponsor
  const RIGHT_LABELS = { "US/graduate_route": "No sponsorship, open to OPT holders", "US/not_sponsored": "No sponsorship offered: check the advert accepts OPT",
    "IE/stamp_1g": "No sponsorship needed: open to Stamp 1G holders" };
  const VERY_SENIOR = /\b(director|head of|vice president|vp|avp|svp|chief|principal|partner)\b/i, SENIOR = /\b(senior|lead|manager|staff|sr\.?)\b/i;
  const JUNIOR = /\b(junior|graduate|trainee|entry[- ]level|associate)\b/i, ASSISTANT = /\b(assistant|intern(ship)?|apprentice(ship)?|placement)\b/i;
  const ENGLISH_COUNTRIES = new Set(["GB", "IE", "US", "MT", "AU"]);   // = jobfeed.classify.ENGLISH_SPEAKING_COUNTRIES
  const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  /** profile: the "candidate" object of a board file (or a profile.json). */
  function Matcher(profile) {
    const TAX = I.taxonomy();
    const years = Number(profile.experience_years || 0), held = (profile.clearance || {}).held || "none", licence = profile.driving_licence ?? null;
    const visa = profile.visa || {}, needsSponsor = visa.sponsorship !== "not_needed", newEntrant = Boolean(visa.new_entrant);
    const englishOnly = profile.english_only ?? true, rights = new Set((visa.work_rights || []).filter(k => RIGHTS[k]).map(k => RIGHTS[k]));
    const needsFor = job => needsSponsor && !rights.has(job.country);
    const tracks = {}, cvFor = {}, every = new Map();
    for (const t of profile.tracks) {
      tracks[t.name] = (t.skills || []).map(s => [s, I.keywordRe(s)]);
      cvFor[t.name] = t.cv || t.name;
      for (const [s, rx] of tracks[t.name]) every.set(s, rx);
    }
    const allSkills = [...every.entries()];
    const roles = profile.roles.map(r => ({ ...r, tokens: I.tokens(r.title), literal: new RegExp("(?<![a-z0-9])" + escRe(r.title.toLowerCase()) + "(?![a-z0-9])") }));
    const also = new Set((profile.also_consider || []).map(a => (typeof a === "string" ? a : a.key)));
    const titleMatch = (fam, title) => fam.titles.some(rx => rx.test(title));

    function titleScore(title) {
      const low = title.toLowerCase(), words = I.tokens(title);
      let best = null;
      for (const r of roles) {
        const shared = [...words].filter(w => r.tokens.has(w)).length, uni = new Set([...words, ...r.tokens]).size;
        let base, why;
        if (r.literal.test(low)) { base = TITLE_LITERAL; why = `title contains the target role “${r.title}”`; }
        else if (r.family && titleMatch(TAX.families[r.family], title)) { base = TITLE_FAMILY; why = `title is a ${TAX.families[r.family].label} role`; }
        else if (shared >= 2 && shared / uni >= 0.6) { base = TITLE_PARTIAL; why = `title is close to “${r.title}”`; }
        else continue;
        const pts = base * (TIER_FACTOR[r.tier] ?? 0.86);
        if (!best || pts > best[0]) best = [pts, { role: r.title, family: r.family || null, tier: r.tier, track: r.track, why }];
      }
      if (best) return best;
      const family = I.familyForTitle(title);
      if (family && also.has(family)) return [TITLE_OTHER, { role: TAX.families[family].label, family, tier: 4, track: null, why: `${TAX.families[family].label}: another route for this skill set` }];
      return null;
    }
    function level(title) {
      if (VERY_SENIOR.test(title) && years < 9) return [0, "0 leadership level", "More senior than the CV"];
      if (SENIOR.test(title)) return years < 5 ? [3, "+3 senior title", "Senior level"] : [8, "+8 senior title", ""];
      if (ASSISTANT.test(title)) return [4, "+4 assistant-level title", "Assistant level, below the CV"];
      if (JUNIOR.test(title)) return [6, "+6 junior/graduate title", ""];
      return [10, "+10 level fits the CV", ""];
    }
    function visaPay(job) {
      if (!needsFor(job)) return { status: "", note: "", required: 0 };
      const country = job.country || "GB", limits = thresholds({ title: job.title || "", country, domain: job.domain || "", sector: job.sector || "" });
      if (!limits) return { status: "", note: "", required: 0 };
      const [full, lowest] = limits, need = newEntrant ? lowest : full, cur = CURRENCY[country] || "";
      const rng = annualRange(job.salary || "", country), who = newEntrant && lowest !== full ? "new-entrant rate" : "minimum";
      if (!rng) return { status: "unstated", required: need, note: `Pay not stated. Skilled Worker ${who} is ${cur}${comma(need)}.` };
      const [low, high] = rng;
      if (low >= need) return { status: "meets", required: need, note: `Pay meets the ${cur}${comma(need)} Skilled Worker ${who}.` };
      if (high >= need) return { status: "partial", required: need, note: `Only the top of the range reaches the ${cur}${comma(need)} ${who}.` };
      return { status: "below", required: need, note: `Pay tops out below the ${cur}${comma(need)} Skilled Worker ${who}: cannot be sponsored at this pay.` };
    }
    function evaluate(job) {
      const title = job.title || "", found = titleScore(title);
      if (!found) return null;
      const [titlePts, info] = found, body = job.full_text || job.description || "", text = `${title}\n${body}`, extract = body.length < EXTRACT_CHARS;
      const skills = info.track ? tracks[info.track] : allSkills;
      const hits = (skills || []).filter(([, rx]) => rx.test(text)).map(([s]) => s);
      const skillPts = (extract ? SKILL_EXTRACT_MAX : SKILL_MAX) * Math.min(1.0, hits.length / SKILLS_FOR_FULL);
      const [levelPts, levelWhy, levelFlag] = level(title);
      const total = pyRound(titlePts + skillPts + levelPts);
      const reasons = [`+${pyRound(titlePts)} ${info.why}`, `+${pyRound(skillPts)} ${hits.length} CV skill(s) found in the advert${extract ? " (extract only)" : ""}`, levelWhy];
      const status = job.sponsorship || "unverified", needs = needsFor(job);
      let [label, rank, offered] = SPONSORSHIP[status] || SPONSORSHIP.unverified;
      const rightLabel = rights.has(job.country) ? RIGHT_LABELS[`${job.country}/${status}`] : null;
      if (rightLabel) [label, rank, offered] = [rightLabel, 3, true];
      const clear = clearance(text, held);
      if (extract && clear.level === "none") clear.label = "No clearance in the extract: check the advert";
      const lic = drivingLicence(text, licence), nationality = nationalityRestriction(text), pay = visaPay(job), family = info.family ? TAX.families[info.family] : null;
      const flags = levelFlag ? [levelFlag] : [], routes = job.sponsor_routes || [];
      const noRoute = job.country === "GB" && routes.length > 0 && status === "licensed_sponsor" && !routes.some(r => r.toLowerCase().includes("skilled worker"));
      if (noRoute) flags.push("Sponsor licence does not list the Skilled Worker route");
      const hidden = [];
      if (englishOnly && !ENGLISH_COUNTRIES.has(job.country) && job.english === false) {
        flags.push("Advert is not in English or asks for another language");
        hidden.push("language");
      }
      if (nationality.restricted) {
        flags.push("Reserved for the country's own nationals");
        hidden.push("nationals_only");
      }
      if (noRoute && needs) hidden.push("no_skilled_worker_route");
      if (clear.blocks) hidden.push("clearance");
      if (needs && !offered) hidden.push("no_sponsorship");
      if (pay.status === "below") hidden.push("pay_below_visa");
      if (lic.status === "missing" && lic.need === "required") hidden.push("licence");
      return {
        match: Math.max(0, Math.min(100, total)), reasons, skills_matched: hits.slice(0, 12), evidence: extract ? "extract" : "full",
        tier: info.tier, role: info.role, family: info.family, family_label: family ? family.label : "", track: info.track,
        cv_to_use: info.track ? cvFor[info.track] || "" : "", sponsorship: status, sponsorship_label: label, sponsorship_rank: rank, sponsorship_offered: offered,
        sponsorability: family ? family.sponsor : "check", sponsorability_note: family ? TAX.sponsorNotes[family.sponsor] || "" : "",
        clearance: clear, driving_licence: lic, nationality, work_mode: workMode(text, job.location), visa_pay: pay, flags, hidden_by_default: hidden,
      };
    }
    return { evaluate, profile };
  }

  // ------------------------------------------------------------------ pipeline.build for the live feed
  const NOISE = new Set(["ltd", "limited", "plc", "llp", "llc", "inc", "incorporated", "corp", "corporation", "sl", "co", "company", "group", "holdings", "uk", "gb", "the", "and", "gmbh", "ag", "bv", "nv", "sa", "sas", "sarl", "srl", "spa", "ab", "as", "oy", "se", "kg"]);
  function normaliseCompany(name) {
    if (!name) return "";
    let n = name.normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase().replace(/&/g, " and ").replace(/\(.*?\)/g, " ").replace(/\./g, "").replace(/[^a-z0-9 ]+/g, " ");
    return n.split(/\s+/).filter(w => w && !NOISE.has(w)).join(" ");
  }
  const dedupeKey = j => [j.title.toLowerCase().split(/\s+/).filter(Boolean).join(" "), normaliseCompany(j.company), (j.location || "").toLowerCase().split(",")[0].trim()].join("|");
  const CHANNEL = { career_site: 2, official: 1, aggregator: 0 };
  const rank = r => [-(SPONSORSHIP[r.sponsorship] || SPONSORSHIP.unverified)[1], CHANNEL[r.channel] || 0, (r.full_text || "").length, r.posted_at];
  const cmpRank = (a, b) => { const x = rank(a), y = rank(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] > y[i] ? 1 : -1; return 0; };

  /** Score feed jobs for one candidate; returns board records (same shape as candidates/data/<slug>.json jobs). */
  function liveJobs(feedJobs, profile, opts) {
    opts = opts || {};
    const m = Matcher(profile), days = opts.days || 7, now = opts.now || Date.now(), countries = new Set(profile.countries || ["GB"]), minMatch = profile.min_match ?? 40;
    const best = new Map();
    for (const rec of feedJobs) {
      const posted = Date.parse(rec.posted_at);
      if (!posted || now - posted > days * 864e5 || !countries.has(rec.country) || !rec.title || !rec.url) continue;
      const ev = m.evaluate(rec);
      if (!ev || ev.match < minMatch + (ev.tier === 4 ? 5 : 0)) continue;
      if (ev.tier === 4 && (!ev.sponsorship_offered || ev.flags.length)) continue;
      const out = Object.fromEntries(Object.entries(rec).filter(([k]) => !["full_text", "tier", "contacts"].includes(k)));
      out.employer_tier = rec.employer_tier ?? rec.tier ?? 3;
      Object.assign(out, ev, { description: (rec.full_text || rec.description || "").slice(0, 500), live: true });
      const key = dedupeKey(rec), prev = best.get(key);
      if (!prev || cmpRank(rec, prev._src) > 0 || (cmpRank(rec, prev._src) === 0 && ev.match > prev.match)) { out._src = rec; best.set(key, out); }
    }
    return [...best.values()].map(r => { delete r._src; return r; });
  }

  return { Matcher, liveJobs, clearance, drivingLicence, annualRange, normaliseCompany, dedupeKey };
});
