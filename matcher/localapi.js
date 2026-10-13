/* A browser-only stand-in for the server API (matcher/app.py): same routes and response shapes, so the interface in
 * app.js runs unchanged. Everything a candidate enters (profile, CVs, tracked applications) is kept in this browser's
 * localStorage and never sent anywhere; matching runs here against data/jobs.json. */
(function () {
  "use strict";
  const KEY = "cjm.v1";
  let D = null, JOBS = [], DIR = [], META = {}, storageOk = true, memory = null, ready = null;

  class HttpError extends Error { constructor(status, message) { super(message); this.status = status; } }
  const fail = (status, message) => { throw new HttpError(status, message); };

  // ---------------------------------------------------------------- storage
  const fresh = () => ({ profile: null, tracks: [], applications: [], nextId: 1 });
  function readStore() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) { const s = JSON.parse(raw); return Object.assign(fresh(), s); }
    } catch (e) { storageOk = false; }
    return memory || (memory = fresh());
  }
  function writeStore(s) {
    memory = s;
    try { localStorage.setItem(KEY, JSON.stringify(s)); storageOk = true; }
    catch (e) { storageOk = false; }  // blocked or full: keep working from memory, tell the candidate
  }

  async function load() {
    const get = async p => { const r = await fetch(p, { cache: "no-cache" }); if (!r.ok) throw new Error(`${p}: ${r.status}`); return r.json(); };
    // The vacancy file is normally next to the page; a host that already publishes one (the sponsor board's
    // data/jobs.json) can point the page at it with window.CJM_JOBS_URL instead of keeping a second copy.
    const [engine, jobs, dir] = await Promise.all([get("data/engine.json"), get(window.CJM_JOBS_URL || "data/jobs.json"), get("data/directory.json")]);
    D = engine; Engine.init(engine);
    JOBS = jobs.jobs;
    // employer key for the career-site directory
    for (const j of JOBS) if (j.ckey === undefined) j.ckey = Engine.baseName(j.company || "");
    DIR = dir; META = { generated_at: jobs.generated_at, window_days: jobs.window_days, count: JOBS.length };
  }

  // ---------------------------------------------------------------- validation (clean_profile in app.py)
  const cleanList = (value, limit = 40, length = 80) => {
    if (typeof value === "string") value = value.split(/[,\n]/);
    if (!Array.isArray(value)) return [];
    const out = [];
    for (const item of value) {
      const t = String(item).split(/\s+/).filter(Boolean).join(" ").slice(0, length);
      if (t && !out.some(o => o.toLowerCase() === t.toLowerCase())) out.push(t);
    }
    return out.slice(0, limit);
  };
  const validDate = v => {
    if (!v) return "";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v) || Number.isNaN(Date.parse(v + "T00:00:00Z"))) fail(400, "Dates must look like 2026-12-31.");
    return v;
  };
  function cleanProfile(raw) {
    const p = JSON.parse(JSON.stringify(D.defaults.profile));
    p.full_name = String(raw.full_name || "").slice(0, 120).trim();
    p.phone = String(raw.phone || "").slice(0, 40).trim();
    const visa = raw.visa_type || "graduate";
    p.visa_type = visa in D.options.visa_types ? visa : "other_visa";
    p.visa_expiry = validDate(String(raw.visa_expiry || ""));
    const mode = raw.sponsorship_mode;
    p.sponsorship_mode = ["required", "preferred", "not_needed"].includes(mode) ? mode : D.options.visa_modes[p.visa_type];
    for (const f of ["new_entrant", "phd", "shortage_role", "graduate_only", "sponsored_only", "open_to_europe", "open_to_india", "consent_privacy"]) p[f] = Boolean(raw[f]);
    p.target_roles = cleanList(raw.target_roles, 15, 80);
    p.keywords = cleanList(raw.keywords, 40, 40);
    p.locations = cleanList(raw.locations, 15, 60);
    p.countries = cleanList(raw.countries, 12, 2).map(c => c.toUpperCase()).filter(c => c in D.options.countries);
    if (!p.countries.length) p.countries = ["GB"];
    p.sectors = cleanList(raw.sectors, 10, 60).filter(s => D.options.sectors.includes(s));
    const table = raw.min_salary && typeof raw.min_salary === "object" ? raw.min_salary : {};
    p.min_salary = {};
    for (const [key, cap] of [["GB", 1e6], ["IE", 1e6], ["EU", 1e6], ["IN", 1000]]) {
      let v = Number(table[key] || 0); if (!Number.isFinite(v)) v = 0;
      v = Math.max(0, Math.min(v, cap)); p.min_salary[key] = key === "IN" ? v : Math.trunc(v);
    }
    return p;
  }

  // ---------------------------------------------------------------- CV files
  const ALLOWED = { ".txt": 1, ".md": 1, ".pdf": 1, ".docx": 1 };
  const extension = n => { const m = /(\.[A-Za-z0-9]+)$/.exec(n); return m ? m[1].toLowerCase() : ""; };
  async function inflateRaw(data) {
    const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }
  async function docxText(bytes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let eocd = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error("not a docx");
    const count = dv.getUint16(eocd + 10, true); let p = dv.getUint32(eocd + 16, true);
    for (let n = 0; n < count; n++) {
      if (dv.getUint32(p, true) !== 0x02014b50) break;
      const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), usize = dv.getUint32(p + 24, true);
      const nlen = dv.getUint16(p + 28, true), elen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true), lho = dv.getUint32(p + 42, true);
      const name = new TextDecoder().decode(bytes.subarray(p + 46, p + 46 + nlen));
      if (name === "word/document.xml") {
        if (usize > 20 * 1024 * 1024) throw new Error("too large");
        const start = lho + 30 + dv.getUint16(lho + 26, true) + dv.getUint16(lho + 28, true);
        const data = bytes.subarray(start, start + csize);
        const xml = new TextDecoder().decode(method === 0 ? data : await inflateRaw(data));
        const doc = new DOMParser().parseFromString(xml, "application/xml");
        const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
        return [...doc.getElementsByTagNameNS(W, "p")].map(par => [...par.getElementsByTagNameNS(W, "t")].map(t => t.textContent).join("")).join("\n");
      }
      p += 46 + nlen + elen + clen;
    }
    throw new Error("no document.xml");
  }
  async function extractText(filename, bytes) {
    const ext = extension(filename);
    if (ext === ".txt" || ext === ".md") return new TextDecoder().decode(bytes);
    if (ext === ".docx") return docxText(bytes);
    return "";  // PDF: the candidate pastes the text
  }
  const fromBase64 = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));

  // ---------------------------------------------------------------- helpers
  const publicTrack = t => ({ id: t.id, name: t.name, priority: t.priority, target_roles: t.target_roles, keywords: t.keywords,
    filename: t.filename || "", uploaded_at: t.uploaded_at || "", chars: (t.text || "").length });
  const candidate = s => s.profile ? Object.assign({}, s.profile, { tracks: s.tracks.map(publicTrack) }) : null;
  const priority = (v, d) => { const n = parseInt(v, 10); return Number.isFinite(n) ? Math.max(1, Math.min(n, D.defaults.max_tracks)) : d; };
  const safeUrl = u => (/^https?:\/\//.test(u || "") ? u : "");
  const today = () => new Date().toISOString().slice(0, 10);
  const q1 = (q, k, d = "") => (q.get(k) === null ? d : q.get(k));

  // ---------------------------------------------------------------- routes
  const routes = [];
  const route = (method, re, fn) => routes.push([method, re, fn]);

  route("GET", /^\/api\/options$/, () => D.options);
  route("GET", /^\/api\/me$/, () => {
    const s = readStore();
    return { email: "this browser", is_admin: false, static: true, storage_ok: storageOk, profile: s.profile || D.defaults.profile,
      has_profile: Boolean(s.profile), tracks: s.tracks.map(publicTrack), feed: META, thresholds: D.thresholds };
  });
  route("PUT", /^\/api\/profile$/, (m, q, body) => {
    const s = readStore(); s.profile = cleanProfile(body); writeStore(s); return { profile: s.profile };
  });

  route("GET", /^\/api\/tracks$/, () => ({ tracks: readStore().tracks.map(publicTrack) }));
  route("POST", /^\/api\/tracks$/, (m, q, body) => {
    const s = readStore();
    if (s.tracks.length >= D.defaults.max_tracks) fail(400, `You can keep up to ${D.defaults.max_tracks} CVs/domains.`);
    const name = String(body.name || "").split(/\s+/).filter(Boolean).join(" ").slice(0, 80);
    if (!name) fail(400, "Give the domain a name, e.g. Business Analyst.");
    const t = { id: s.nextId++, name, priority: priority(body.priority, s.tracks.length + 1), target_roles: cleanList(body.target_roles || [name], 10, 80),
      keywords: cleanList(body.keywords, 40, 40), filename: "", text: "", uploaded_at: "" };
    s.tracks.push(t); s.tracks.sort((a, b) => a.priority - b.priority || a.id - b.id); writeStore(s);
    return { id: t.id, tracks: s.tracks.map(publicTrack) };
  });
  route("PUT", /^\/api\/tracks\/(\d+)$/, (m, q, body) => {
    const s = readStore(); const t = s.tracks.find(x => x.id === +m[1]); if (!t) fail(404, "Track not found.");
    t.name = String(body.name === undefined ? t.name : body.name).split(/\s+/).filter(Boolean).join(" ").slice(0, 80) || t.name;
    t.priority = priority(body.priority, t.priority);
    t.target_roles = cleanList(body.target_roles === undefined ? t.target_roles : body.target_roles, 10, 80);
    t.keywords = cleanList(body.keywords === undefined ? t.keywords : body.keywords, 40, 40);
    s.tracks.sort((a, b) => a.priority - b.priority || a.id - b.id); writeStore(s);
    return { tracks: s.tracks.map(publicTrack) };
  });
  route("DELETE", /^\/api\/tracks\/(\d+)$/, m => {
    const s = readStore(); if (!s.tracks.some(x => x.id === +m[1])) fail(404, "Track not found.");
    s.tracks = s.tracks.filter(x => x.id !== +m[1]); writeStore(s); return { tracks: s.tracks.map(publicTrack) };
  });
  route("GET", /^\/api\/tracks\/(\d+)\/resume$/, () => fail(404, "The test version keeps only the text of your CV, not the file. Use your original file to apply."));
  route("POST", /^\/api\/tracks\/(\d+)\/resume$/, async (m, q, body) => {
    const s = readStore(); const t = s.tracks.find(x => x.id === +m[1]); if (!t) fail(404, "Track not found.");
    const filename = String(body.filename || "cv.txt").split(/[\\/]/).pop().slice(0, 120) || "cv.txt";
    if (!(extension(filename) in ALLOWED)) fail(400, "Upload a .docx, .pdf, .txt or .md file, or paste your CV text.");
    let bytes; try { bytes = fromBase64(String(body.data || "")); } catch (e) { fail(400, "The file could not be read."); }
    if (!bytes.length || bytes.length > 5 * 1024 * 1024) fail(400, "Files must be between 1 byte and 5 MB.");
    let text; try { text = await extractText(filename, bytes); } catch (e) { fail(400, "That file could not be read. Try pasting the text instead."); }
    text = (String(body.text || "").trim() || text).slice(0, 200000);
    t.filename = filename; t.text = text; t.uploaded_at = new Date().toISOString();
    const kws = Engine.extractKeywords(text);
    if (kws.length && !t.keywords.length) t.keywords = kws.slice(0, 30);
    writeStore(s);
    return { filename, keywords: kws, needs_text: !text.trim(), tracks: s.tracks.map(publicTrack) };
  });
  route("DELETE", /^\/api\/tracks\/(\d+)\/resume$/, m => {
    const s = readStore(); const t = s.tracks.find(x => x.id === +m[1]); if (!t) fail(404, "Track not found.");
    t.filename = t.text = t.uploaded_at = ""; writeStore(s); return { ok: true };
  });

  route("POST", /^\/api\/suggestions$/, (m, q, body) => {
    const s = readStore(); const cand = candidate(s); if (!cand) fail(409, "Complete your profile first.");
    let rows = s.tracks.filter(t => t.text);
    if (body.track_id) rows = rows.filter(t => t.id === body.track_id);
    const text = String(body.text || "").trim() || rows.map(t => t.text).join("\n");
    if (!text.trim()) fail(400, "Upload a CV (or paste text) first, then ask for suggestions.");
    const taken = new Set(s.tracks.map(t => t.name.toLowerCase()));
    const out = Engine.suggestRoles(text, Engine.countVacancies(JOBS, cand), 8);
    out.forEach(i => { i.already_added = taken.has(i.role.toLowerCase()); });
    return { suggestions: out, feed_jobs: JOBS.length };
  });

  route("GET", /^\/api\/jobs$/, (m, q) => {
    const s = readStore(); const cand = candidate(s); if (!cand) fail(409, "Complete your profile first.");
    const int = (k, d, lo, hi) => { const n = parseInt(q1(q, k, ""), 10); return Number.isFinite(n) ? Math.max(lo, Math.min(n, hi)) : d; };
    const track = q1(q, "track"); const text = q1(q, "q").trim();
    const matches = Engine.matchJobs(JOBS, cand, { minMatch: int("min_match", text ? 0 : 30, 0, 100), hideBelow: q1(q, "show_below", "0") !== "1",
      query: q1(q, "q"), trackId: /^\d+$/.test(track) ? +track : null, country: q1(q, "country").toUpperCase().slice(0, 2),
      sponsoredOnly: q1(q, "sponsored_only", "0") === "1" });
    const applied = Object.fromEntries(s.applications.map(a => [a.job_id, a.status]));
    const by = {}; for (const j of matches) by[j.country] = (by[j.country] || 0) + 1;
    const offset = int("offset", 0, 0, 100000), limit = int("limit", 25, 1, 100);
    const page = matches.slice(offset, offset + limit).map(j => {
      const site = j.employer_site || (j.channel !== "career_site" ? Engine.linkFor(DIR, j) : "");
      const out = Object.assign({}, j, { url: safeUrl(j.url), employer_site: safeUrl(site), application_status: applied[j.id] || "", contacts: j.contacts || [] });
      if (!out.contacts.length && j.company)
        out.recruiter_search = "https://www.linkedin.com/search/results/people/?keywords=" + encodeURIComponent(`${j.company} recruiter OR "talent acquisition" OR "hiring manager" ${j.title || ""}`);
      return out;
    });
    return { total: matches.length, offset, jobs: page, by_country: by };
  });

  route("GET", /^\/api\/employers$/, (m, q) => {
    const s = readStore();
    return Engine.directoryListing(DIR, JOBS, candidate(s), { q: q1(q, "q"), country: q1(q, "country").toUpperCase().slice(0, 2), category: q1(q, "category") });
  });

  const appOut = a => ({ job_id: a.job_id, status: a.status, applied_on: a.applied_on, closing_date: a.closing_date, notes: a.notes, updated_at: a.updated_at, job: a.job });
  route("GET", /^\/api\/applications$/, () => ({ applications: readStore().applications.slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(appOut) }));
  route("POST", /^\/api\/applications$/, (m, q, body) => {
    const s = readStore(); const status = body.status || "saved";
    if (!D.options.statuses.includes(status)) fail(400, "Unknown status.");
    const id = String(body.job_id || ""); let rec = s.applications.find(a => a.job_id === id);
    if (!rec) {
      const job = JOBS.find(j => j.id === id); if (!job) fail(404, "That job is no longer in the feed.");
      const snap = {}; for (const k of ["id", "title", "company", "location", "country", "url", "salary", "posted_at", "contacts", "sponsorship"]) snap[k] = job[k] ?? null;
      snap.track = String(body.track || "").slice(0, 80); snap.cv = String(body.cv || "").slice(0, 120);
      rec = { job_id: id, job: snap }; s.applications.push(rec);
    }
    let appliedOn = validDate(String(body.applied_on || ""));
    if (status === "applied" && !appliedOn) appliedOn = today();
    Object.assign(rec, { status, applied_on: appliedOn, closing_date: validDate(String(body.closing_date || "")), notes: String(body.notes || "").slice(0, 2000), updated_at: new Date().toISOString() });
    writeStore(s); return { ok: true, status, applied_on: appliedOn };
  });
  route("DELETE", /^\/api\/applications\/(.+)$/, m => {
    const s = readStore(); s.applications = s.applications.filter(a => a.job_id !== decodeURIComponent(m[1])); writeStore(s); return { ok: true };
  });

  const exportData = () => {
    const s = readStore();
    return { app: "candidate-job-matcher", version: 1, exported_at: new Date().toISOString(), profile: s.profile,
      tracks: s.tracks.map(t => ({ name: t.name, priority: t.priority, target_roles: t.target_roles, keywords: t.keywords, filename: t.filename, text: t.text })),
      applications: s.applications.map(appOut) };
  };
  route("GET", /^\/api\/export$/, () => new Blob([JSON.stringify(exportData(), null, 2)], { type: "application/json" }));
  route("DELETE", /^\/api\/account$/, () => { writeStore(fresh()); return { ok: true }; });

  // ---------------------------------------------------------------- import / personas
  function importData(data) {
    if (!data || typeof data !== "object" || !data.profile) fail(400, "That file isn't a Candidate Job Matcher export.");
    const s = fresh(); s.profile = cleanProfile(data.profile);
    for (const t of (data.tracks || []).slice(0, D.defaults.max_tracks)) {
      s.tracks.push({ id: s.nextId++, name: String(t.name || "Domain").slice(0, 80), priority: priority(t.priority, s.tracks.length + 1),
        target_roles: cleanList(t.target_roles, 10, 80), keywords: cleanList(t.keywords, 40, 40), filename: String(t.filename || "").slice(0, 120),
        text: String(t.text || "").slice(0, 200000), uploaded_at: t.text ? new Date().toISOString() : "" });
    }
    s.applications = (data.applications || []).filter(a => a && a.job_id && a.job).map(a => ({ job_id: String(a.job_id), status: D.options.statuses.includes(a.status) ? a.status : "saved",
      applied_on: a.applied_on || "", closing_date: a.closing_date || "", notes: String(a.notes || "").slice(0, 2000), job: a.job, updated_at: a.updated_at || new Date().toISOString() }));
    writeStore(s);
  }
  async function loadPersona(key) {
    const r = await fetch(`personas/${encodeURIComponent(key)}.json`, { cache: "no-cache" });
    if (!r.ok) fail(404, "That sample candidate isn't available.");
    const p = await r.json();
    const d = new Date(); d.setUTCDate(d.getUTCDate() + (p.visa_expiry_days || 0));
    if (p.visa_expiry_days !== undefined) p.profile.visa_expiry = d.toISOString().slice(0, 10);
    p.profile.consent_privacy = true;
    importData({ profile: p.profile, tracks: p.tracks, applications: [] });
  }

  async function call(method, path, body) {
    if (!D) await ready;
    const url = new URL(path, "http://local");
    for (const [m, re, fn] of routes) {
      const hit = re.exec(url.pathname);
      if (m === method && hit) return fn(hit, url.searchParams, body || {});
    }
    fail(404, "Not found");
  }
  const personas = async () => { const r = await fetch("personas/index.json", { cache: "no-cache" }); return r.ok ? r.json() : []; };
  ready = load();
  window.LocalApi = { call, ready, importData, loadPersona, personas, exportData, get storageOk() { return storageOk; }, HttpError };
})();
