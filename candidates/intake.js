/* Browser port of candidateboard/{taxonomy,cv,intake}.py. Role families come from candidateboard/roles.json, the same file the
 * Python scan reads, and tests/test_intake_js.py checks both produce the same profile for the same CV text. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CandidateIntake = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const STOP = new Set(["and", "the", "of", "for", "a", "an", "in", "to", "with", "or", "&", "/", "-", "senior", "junior", "lead", "graduate", "associate", "entry", "level"]);
  const GENERIC = ["word", "excel", "support", "customer", "sales", "reporting", "coordination", "sap", "plan", "content", "records", "documentation", "administration", "tickets?", "sla"];
  const SKILLS_PER_TRACK = 60, SUGGEST_MIN_STRENGTH = 30;
  const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  let TAX = null, REGIONS = { default: ["GB"], regions: { GB: { label: "United Kingdom", countries: ["GB"] } } };

  const tokens = text => new Set((text.toLowerCase().match(/[a-z0-9+#]+/g) || []).filter(w => !STOP.has(w) && w.length > 1));
  const inter = (a, b) => [...a].filter(x => b.has(x)).length;
  const union = (a, b) => new Set([...a, ...b]).size;
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);   // code-point order, as Python sorts strings
  const keywordRe = term => new RegExp("(?<![a-z0-9])(?:" + term + ")(?![a-z0-9])", "i");
  function pyRound1(x) {                                    // Python rounds exact halves to even
    const s = x * 10, r = Math.round(s);
    return (Math.abs(s % 1) === 0.5 ? 2 * Math.round(s / 2) : r) / 10;
  }

  function init(roles, regions) {
    if (regions) REGIONS = regions;
    const families = {};
    for (const [key, f] of Object.entries(roles.families)) {
      families[key] = { key, label: f.label, titles: f.titles.map(p => new RegExp(p, "i")),
        keywords: f.keywords.map(k => [k, keywordRe(k)]), searches: f.searches, adjacent: f.adjacent || [], sponsor: f.sponsor || "check" };
    }
    TAX = { families, sponsorNotes: roles.sponsor_notes };
    return api;
  }

  function titleMatch(fam, title) {
    let best = 0;
    for (const rx of fam.titles) { const m = rx.exec(title); if (m) best = Math.max(best, m[0].length); }
    return best;
  }
  function familyForTitle(title) {
    let best = [0, null];
    for (const [k, f] of Object.entries(TAX.families)) { const n = titleMatch(f, title); if (n > best[0] || (n === best[0] && n > 0 && cmp(k, best[1]) > 0)) best = [n, k]; }
    if (best[0]) return best[1];
    const want = tokens(title);
    if (!want.size) return null;
    let top = 0, key = null;
    for (const [k, f] of Object.entries(TAX.families)) {
      for (const cand of [...f.searches, f.label]) {
        const have = tokens(cand);
        if (have.size && inter(want, have) >= 2) { const j = inter(want, have) / union(want, have); if (j > top) { top = j; key = k; } }
      }
    }
    return top >= 0.6 ? key : null;
  }

  // ------------------------------------------------------------------ CV scan
  const rangeRe = () => /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\s*[–—-]\s*(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})|(present|current|now|date))/gi;
  const LEVEL_YEARS = { junior: 1, mid: 4, senior: 8, lead: 12 };   // = candidateboard.intake.LEVEL_YEARS
  function experienceMonths(text, today) {
    today = today || new Date();
    const spans = [];
    for (const m of text.matchAll(rangeRe())) {
      const start = Number(m[2]) * 12 + MONTHS.indexOf(m[1].toLowerCase()) + 1;
      const end = m[3] ? Number(m[4]) * 12 + MONTHS.indexOf(m[3].toLowerCase()) + 1 : today.getFullYear() * 12 + today.getMonth() + 1;
      if (end >= start) spans.push([start, end + 1]);
    }
    spans.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    let total = 0, curEnd = null;
    for (const [s, e] of spans) {
      if (curEnd === null || s > curEnd) { total += e - s; curEnd = e; }
      else if (e > curEnd) { total += e - curEnd; curEnd = e; }
    }
    return total;
  }
  const EDU = [["PhD", /\b(ph\.?d|doctorate)\b/i], ["Master's", /\b(mba|m\.?sc|m\.?a\.?|m\.?eng|master'?s?|m\.?tech)\b/i], ["Bachelor's", /\b(b\.?tech|b\.?e\.?|b\.?sc|b\.?a\.?|bachelor'?s?|b\.?eng)\b/i]];
  function education(text) {
    for (const [label, rx] of EDU) {
      const m = rx.exec(text);
      if (m) return m[0].toLowerCase() === "mba" ? `${label} (MBA)` : label;
    }
    return "";
  }
  const lines = text => text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  const titleCase = s => s.toLowerCase().replace(/(^|[\s-])([a-z])/g, (_, p, c) => p + c.toUpperCase());
  function nameAndHeadline(text) {
    const ls = lines(text);
    let name = ls.length && ls[0].split(/\s+/).length <= 5 && !/[@\d]/.test(ls[0]) ? ls[0] : "";
    let headline = "";
    for (const l of ls.slice(1, 4)) if (!/[@+]|\d{5}|linkedin/i.test(l)) { headline = l; break; }
    if (name && name === name.toUpperCase() && /[A-Z]/.test(name)) name = titleCase(name);
    return [name, headline];
  }
  function titleText(text) {
    const ls = lines(text);
    return [...ls.slice(0, 3), ...ls.slice(3).filter(l => rangeRe().test(l) || /\S\s\|\s\S/.test(l))].join("\n");
  }
  function scan(text, today) {
    const titles = titleText(text), families = {};
    for (const [key, fam] of Object.entries(TAX.families)) {
      const titleHits = fam.titles.filter(rx => rx.test(titles)).length;
      const found = fam.keywords.filter(([, rx]) => rx.test(text)).map(([t]) => t);
      const strength = Math.min(100, 30 * Math.min(titleHits, 2) + 7 * found.length);
      if (strength) families[key] = { strength, title_hits: titleHits, skills: found };
    }
    const [name, headline] = nameAndHeadline(text);
    return { name, headline, months: experienceMonths(text, today), education: education(text), families };
  }

  function tierFamilies(families) {
    const strength = Object.fromEntries(Object.entries(families).map(([k, v]) => [k, v.strength]));
    const ranked = Object.keys(strength).sort((a, b) => strength[b] - strength[a]);
    const tiers = {};
    for (const k of ranked.slice(0, 3)) if (strength[k] >= 55) tiers[k] = 1;
    const adj = (a, b) => TAX.families[a].adjacent.includes(b);
    for (const k of ranked) {
      if (k in tiers) continue;
      const nearT1 = Object.entries({ ...tiers }).some(([t, tr]) => tr === 1 && (adj(t, k) || adj(k, t)));
      if (strength[k] >= 30 || (nearT1 && strength[k] >= 15)) tiers[k] = 2;
    }
    for (const k of ranked) {
      if (k in tiers) continue;
      if (strength[k] >= 12 || Object.entries({ ...tiers }).some(([t, tr]) => tr <= 2 && adj(t, k))) tiers[k] = 3;
    }
    for (const t of Object.keys(tiers).filter(t => tiers[t] <= 2)) for (const k of TAX.families[t].adjacent) if (!(k in tiers)) tiers[k] = 4;
    for (const [k, s] of Object.entries(strength)) if (!(k in tiers) && s >= 6) tiers[k] = 4;
    return tiers;
  }

  const MAX_LOOSE_WORDS = 8, MAX_LOOSE_CHARS = 70;
  /** One list item -> its role titles: (notes) dropped; "A / B" is two roles; "Marketing Executive / Coordinator" too. */
  function expandTitle(raw) {
    const title = raw.replace(/\([^)]*\)/g, "").split("\u200b").join("").split(/\s+/).filter(Boolean).join(" ").replace(/^[\s—–-]+|[\s—–-]+$/g, "");
    const parts = title.split(/\s+\/\s+/).map(p => p.trim()).filter(Boolean), out = [];
    parts.forEach((part, i) => {
      if (i && part.split(/\s+/).length === 1 && parts[0].split(/\s+/).length >= 2) part = [...parts[0].split(/\s+/).slice(0, -1), part].join(" ");
      out.push(part);
    });
    return out;
  }
  /** A list with no bullets or numbers: each short line is a title; a comma-separated line of short items is several. */
  function looseRoles(text) {
    const roles = [];
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.split("\u200b").join("").split(/\s+/).filter(Boolean).join(" ");
      if (!line || line.includes("@") || line.toLowerCase().includes("http")) continue;
      let pieces;
      if (/[;,]/.test(line)) {
        pieces = line.split(/[;,]/).map(x => x.trim()).filter(Boolean);
        if (!pieces.every(x => x.split(/\s+/).length <= 5)) continue;        // a sentence with commas, not a list of titles
      } else pieces = [line];
      for (let piece of pieces) {
        piece = piece.replace(/\.+$/, "").trim();
        if (!piece || piece.length > MAX_LOOSE_CHARS || piece.split(/\s+/).length > MAX_LOOSE_WORDS) continue;
        if (!/[A-Za-z]/.test(piece) || piece.endsWith(":")) continue;
        for (const title of expandTitle(piece)) roles.push({ title, section: "" });
      }
    }
    return roles;
  }
  /** The role families a document's wording points to (strongest first), for a list that names no job titles. */
  function documentDomains(text, limit = 3) {
    const found = scan(text).families;
    return Object.keys(found).sort((a, b) => found[b].strength - found[a].strength || cmp(a, b)).filter(k => found[k].strength >= 12).slice(0, limit);
  }
  /** A list of suitable roles: bullet or numbered lines are titles, other lines are section headings; with no bullets, line by line. */
  function parseRoleList(text) {
    const roles = []; let section = "", bulleted = false;
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue;
      const m = /^\s*(?:[●•▪◦*\-–]|\d{1,2}[.)])\s*(.+)$/.exec(line);
      if (!m) { section = line.trim().replace(/^[●•]+|[●•]+$/g, "").trim(); continue; }
      bulleted = true;
      for (const title of expandTitle(m[1])) roles.push({ title, section });
    }
    return bulleted ? roles : looseRoles(text);
  }

  /** Add the positions in a document (the text of an attached PDF / Word / text file) to an existing profile (results page).
   *  Tier comes from how well the CV evidences that kind of role; a section named after a CV picks that CV. Returns the roles added. */
  function addPositions(profile, text) {
    const have = new Set(profile.roles.map(r => r.title.toLowerCase())), trackNames = profile.tracks.map(t => t.name), added = [];
    let items = parseRoleList(text);
    if (items.length < 2) {      // no job titles in the document: read its keywords and search the domains they point to
      const viaKeywords = [];
      for (const fam of documentDomains(text)) for (const t of TAX.families[fam].searches.slice(0, 2)) viaKeywords.push({ title: t, section: "", source: "document keywords" });
      items = [...items, ...viaKeywords];
    }
    for (const item of items) {
      const title = cleanTitles([item.title])[0];
      if (!title || have.has(title.toLowerCase())) continue;
      const family = familyForTitle(title), named = item.section ? trackForSection(item.section, trackNames) : null;
      const sameFamily = profile.roles.find(r => family && r.family === family);
      let tier = family ? ((profile.family_evidence || {})[family]?.tier ?? 3) : 3;
      if (item.section && !named) tier = Math.max(tier, 3);
      const role = { title, family, tier: Math.min(tier, 3), track: named || (sameFamily ? sameFamily.track : trackNames[0]), source: item.source || "attached document" };
      profile.roles.push(role); added.push(role); have.add(title.toLowerCase());
    }
    profile.roles.sort((a, b) => a.tier - b.tier || cmp(a.track, b.track) || cmp(a.title, b.title));
    return added;
  }

  // ------------------------------------------------------------------ profile
  function genericTerms() {
    const counts = {};
    for (const f of Object.values(TAX.families)) for (const [t] of f.keywords) counts[t] = (counts[t] || 0) + 1;
    return new Set([...GENERIC, ...Object.keys(counts).filter(t => counts[t] >= 3)]);
  }
  function trackForSection(section, tracks) {
    const words = tokens(section); words.delete("cv");
    let best = null, top = 0;
    for (const t of tracks) {
      const have = tokens(t), score = have.size ? inter(words, have) / have.size : 0;
      if (score > top) { best = t; top = score; }
    }
    return top >= 0.67 ? best : null;
  }
  const slugify = name => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

  const MAX_EXTRA_ROLES = 30, MAX_TITLE_CHARS = 80;
  /** Job titles a candidate typed: whitespace collapsed, blanks and repeats dropped, capped in number and length. */
  function cleanTitles(raw) {
    const out = [];
    for (const item of raw || []) {
      const title = String(item).split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_TITLE_CHARS).replace(/^[ ,;]+|[ ,;]+$/g, "");
      if (title && !out.some(t => t.toLowerCase() === title.toLowerCase())) out.push(title);
    }
    return out.slice(0, MAX_EXTRA_ROLES);
  }
  /** Every job title the role list knows (family searches), for type-ahead suggestions. */
  function suggestions() {
    return [...new Set(Object.values(TAX.families).flatMap(f => f.searches))].sort(cmp);
  }
  /** Add roles the candidate wants to an existing profile (results page): first choice, on the best-fitting CV track. */
  function addRoles(profile, titles) {
    const have = new Set(profile.roles.map(r => r.title.toLowerCase())), added = [];
    for (const title of cleanTitles(titles)) {
      if (have.has(title.toLowerCase())) continue;
      const family = familyForTitle(title);
      const sameFamily = profile.roles.find(r => family && r.family === family);
      const role = { title, family, tier: 1, track: sameFamily ? sameFamily.track : profile.tracks[0].name, source: "added by candidate" };
      profile.roles.push(role); added.push(role); have.add(title.toLowerCase());
    }
    profile.roles.sort((a, b) => a.tier - b.tier || cmp(a.track, b.track) || cmp(a.title, b.title));
    return added;
  }

  function expandRegions(keys) {
    keys = [...new Set(keys && keys.length ? keys : REGIONS.default)];
    const unknown = keys.filter(k => !REGIONS.regions[k]);
    if (unknown.length) throw new Error(`unknown location(s) ${unknown}`);
    return [keys, [...new Set(keys.flatMap(k => REGIONS.regions[k].countries))]];
  }

  /** cvs: [{track, filename, text}]. opts mirror candidateboard.intake.build_profile. */
  function buildProfile(cvs, rolesText, opts) {
    opts = opts || {};
    const [locations, countries] = expandRegions(opts.regions);
    const scans = cvs.map(c => ({ ...c, s: scan(c.text, opts.today) }));
    const combined = {};
    for (const { track, s } of scans) for (const [fam, ev] of Object.entries(s.families)) if (!(fam in combined) || ev.strength > combined[fam].strength) combined[fam] = { ...ev, track };
    const tiers = tierFamilies(combined), generic = genericTerms(), trackNames = cvs.map(c => c.track);
    const tracks = scans.map(({ track, filename, s }) => {
      const skills = [];
      for (const [, ev] of Object.entries(s.families).sort((a, b) => b[1].strength - a[1].strength)) {
        if (ev.strength >= 12) for (const k of ev.skills) if (!skills.includes(k) && !generic.has(k)) skills.push(k);
      }
      return { name: track, cv: filename, headline: s.headline, skills: skills.slice(0, SKILLS_PER_TRACK) };
    });
    const first = scans[0].s, roles = [], seen = new Set();
    const add = (title, family, source, section, firstChoice) => {
      if (seen.has(title.toLowerCase())) return;
      seen.add(title.toLowerCase());
      const named = section ? trackForSection(section, trackNames) : null;
      const track = named || (family in combined ? combined[family].track : trackNames[0]);
      let tier = family ? (tiers[family] ?? 3) : 3;
      if (section && !named) tier = Math.max(tier, 3);
      if (firstChoice) tier = 1;          // a role the candidate named themselves is always searched first
      roles.push({ title, family, tier: Math.min(tier, 3), track, source });
    };
    for (const title of cleanTitles(opts.extraRoles)) add(title, familyForTitle(title), "added by candidate", "", true);
    const items = rolesText ? parseRoleList(rolesText) : [];
    for (const item of items) add(item.title, familyForTitle(item.title), "recruiter list", item.section);
    if (rolesText && items.length < 2) for (const fam of documentDomains(rolesText)) for (const t of TAX.families[fam].searches.slice(0, 2)) add(t, fam, "document keywords", "");
    const covered = new Set(roles.map(r => r.family));
    for (const [fam, tier] of Object.entries(tiers)) {
      if (tier <= 2 && !covered.has(fam) && combined[fam].strength >= SUGGEST_MIN_STRENGTH) for (const t of TAX.families[fam].searches.slice(0, 2)) add(t, fam, "suggested from CV", "");
    }
    roles.sort((a, b) => a.tier - b.tier || cmp(a.track, b.track) || cmp(a.title, b.title));
    const months = Math.max(...scans.map(c => c.s.months));
    const have = new Set(roles.map(r => r.family));
    return {
      slug: opts.slug || slugify(opts.name || first.name), name: opts.name || first.name, headline: first.headline,
      base_location: opts.location || "", country: countries[0], locations, countries, english_only: opts.englishOnly ?? true, current_status: opts.status || "",
      experience_years: LEVEL_YEARS[opts.experienceLevel] ?? pyRound1(months / 12), experience_level: opts.experienceLevel || "", education: first.education,
      visa: opts.visa || { type: "", label: "", expires: "", sponsorship: "required", new_entrant: false },
      clearance: { held: opts.clearance || "none" }, driving_licence: opts.drivingLicence ?? null,
      window_days: 7, min_match: 40, india_min_lpa: opts.indiaMinLpa ?? 8, tracks, roles,
      also_consider: Object.keys(tiers).filter(k => tiers[k] === 4 || !have.has(k)).sort(cmp),
      family_evidence: Object.fromEntries(Object.entries(combined).sort((a, b) => b[1].strength - a[1].strength).filter(([, v]) => v.strength >= 12).map(([k, v]) => [k, { strength: v.strength, tier: tiers[k] ?? null }])),
      notes: opts.notes || "",
    };
  }

  const api = { init, addPositions, documentDomains, cleanTitles, suggestions, addRoles, taxonomy: () => TAX, regions: () => REGIONS.regions, expandRegions, keywordRe, tokens, scan, tierFamilies, parseRoleList, familyForTitle, buildProfile, experienceMonths, slugify, labels: () => Object.fromEntries(Object.entries(TAX.families).map(([k, f]) => [k, { label: f.label, sponsor: f.sponsor }])) };
  return api;
});
