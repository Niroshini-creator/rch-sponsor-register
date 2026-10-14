"use strict";
/* Candidate board viewer. /candidates/ lists candidates; /candidates/?c=<slug> shows one candidate's matched roles.
 * Everything is read from data/<slug>.json (built by `python -m candidateboard build`); nothing is sent anywhere. */

const $app = document.getElementById("app");
const $header = document.getElementById("header");

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}
const badge = (text, kind, title) => h("span", { class: `badge ${kind || ""}`, title }, text);
const money = (s, country = "GB") => (s && /^\d/.test(s) ? `${{ GB: "£", IE: "€" }[country] || ""}${s}` : s || "");
const COUNTRY_NAMES = new Intl.DisplayNames(["en"], { type: "region" });
const countryName = code => { try { return COUNTRY_NAMES.of(code); } catch { return code; } };
const ENGLISH_COUNTRIES = ["GB", "IE", "US", "MT", "AU"];
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}
function ago(iso) {
  const d = (Date.now() - new Date(iso).getTime()) / 864e5;
  if (d < 1) return "today";
  return d < 2 ? "yesterday" : `${Math.floor(d)} days ago`;
}
function monthsLeft(expires) {
  if (!expires) return null;
  const [y, m] = expires.split("-").map(Number);
  const now = new Date();
  return (y - now.getFullYear()) * 12 + (m - 1 - now.getMonth());   // counted from the start of the month: the cautious reading
}
function monthName(expires) {
  const [y, m] = expires.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-GB", { month: "short", year: "numeric" });
}

// ------------------------------------------------------------------------------------------ candidate list
async function listView() {
  document.title = "Recruiter boards";
  $header.replaceChildren(h("div", {}, h("a", { class: "back", href: "./" }, "← Find roles for a CV"), h("h1", {}, "Recruiter boards"),
    h("p", { class: "muted small" }, "Saved candidates: roles from the last 7 days matched to each one's CV, visa and clearance.")));
  const { candidates } = await getJSON("data/index.json");
  if (!candidates.length) { $app.replaceChildren(h("p", { class: "empty" }, "No saved boards yet.")); return; }
  $app.replaceChildren(h("div", { class: "grid2", style: "margin-top:14px" }, candidates.map(c =>
    h("a", { class: "panel cand", href: `?c=${encodeURIComponent(c.slug)}` },
      h("h2", {}, c.name), h("p", { class: "muted small" }, c.headline),
      h("ul", { class: "chips" }, h("li", { class: "chip" }, c.visa || "Visa not set"),
        c.visa_expires ? h("li", { class: "chip warn" }, `until ${monthName(c.visa_expires)}`) : null,
        h("li", { class: "chip ok" }, `${c.published} roles`)),
      h("p", { class: "small muted" }, `Tier 1: ${c.by_tier?.[1] ?? 0} · Tier 2: ${c.by_tier?.[2] ?? 0} · Tier 3: ${c.by_tier?.[3] ?? 0} · Other: ${c.by_tier?.[4] ?? 0}`,
        c.generated_at ? ` · updated ${ago(c.generated_at)}` : " · not built yet")))));
}

// ------------------------------------------------------------------------------------------ one candidate
const TABS = [["1", "Tier 1 · Core"], ["2", "Tier 2 · Close"], ["3", "Tier 3 · Stretch"], ["4", "Other roles"], ["employers", "Employers"], ["cv", "CV scan"]];
const state = { tab: "1", q: "", spons: "offered", min: 0, days: 7, sort: "match", showBlocked: false, sector: "", etier: "", source: "direct", country: "" };
// By default only genuine employers are shown: employer career sites and the official boards (NHS Jobs, councils and Civil
// Service departments, universities, schools). Job boards (Reed, Adzuna, Arbeitnow) are one click away.
const SOURCE_FILTERS = [["direct", "Employer career sites, NHS, public sector, universities & schools"], ["noadzuna", "Also job boards, except Adzuna"], ["all", "Everything, including Adzuna"]];
const sourceOk = (j, mode = state.source) => mode === "all" || (mode === "direct" ? j.channel !== "aggregator" : j.source !== "Adzuna");
let data = null;
const live = { status: "pending", feedTime: "", added: 0, error: "", baseJobs: [] };
const LIVE_RECHECK_MS = 30 * 60 * 1000;

// ------------------------------------------------------------------------------------------ live matching
// The built board is rebuilt daily; the shared feed is rebuilt every two hours. Score that feed here, in the browser, with
// the same engine (match.js), and add the roles the daily build does not have yet.
function feedUrls() {
  const urls = [];
  if (location.hostname.endsWith(".github.io")) {
    const owner = location.hostname.split(".")[0], repo = location.pathname.split("/")[1];
    if (owner && repo) urls.push(`https://raw.githubusercontent.com/${owner}/${repo}/feed/data/jobs.json`);
  }
  return [...urls, "../data/jobs.json"];
}
async function loadFeed() {
  let lastErr;
  for (const url of feedUrls()) {
    try { return await getJSON(url); } catch (err) { lastErr = err; }
  }
  throw lastErr;
}
async function runLive(force) {
  try {
    if (!window.CandidateMatch) throw new Error("matcher not loaded");
    const roles = await getJSON("../candidateboard/roles.json");
    CandidateIntake.init(roles);
    const feed = await loadFeed();
    await loadCareerLinks();
    data.feedSources = feed.sources || {};
    if (!force && live.feedTime === feed.generated_at && live.status === "ok") return;
    const fresh = CandidateMatch.liveJobs(feed.jobs, data.candidate, { days: data.window_days });
    const ids = new Set(live.baseJobs.map(j => j.id)), keys = new Set(live.baseJobs.map(CandidateMatch.dedupeKey));
    const added = fresh.filter(j => !ids.has(j.id) && !keys.has(CandidateMatch.dedupeKey(j)));
    data.jobs = [...live.baseJobs, ...added];
    Object.assign(live, { status: "ok", feedTime: feed.generated_at, added: added.length, error: "" });
  } catch (err) {
    data.jobs = live.baseJobs;
    Object.assign(live, { status: "error", error: err.message, added: 0 });
  }
  data.sources["Live feed"] = live.status === "ok" ? { status: "ok", count: live.added } : { status: "error", error: live.error };
  if (live.mode === "self" && live.firstPaint && live.status === "ok") {
    live.firstPaint = false;
    const first = ["1", "2", "3", "4"].find(t => data.jobs.some(j => String(j.tier) === t && visible({ ...j }, t)));
    if (first) state.tab = first;
  }
  render();
}
function liveBanner() {
  if (live.mode === "self") {
    const text = { pending: "Matching your CV against this week's vacancies…",
      ok: `${data.jobs.length} vacancies matched from the live feed (updated ${ago(live.feedTime)}). Press Apply to go to the employer's advert. By default only genuine employers are shown (career sites, NHS, public sector, universities, schools) and only roles with sponsorship or a sponsor licence; change “Where advertised” or “Sponsorship” below to see more.`,
      error: `Could not load the vacancies (${live.error}). Check your connection and press Refresh.` }[live.status];
    return h("div", { class: "panel small bar", style: "margin:10px 0 0;align-items:center" },
      h("span", { class: `badge ${live.status === "ok" ? "ok" : live.status === "error" ? "warn" : ""}` }, live.status === "ok" ? "Live" : live.status === "error" ? "Offline" : "…"), text,
      h("button", { class: "btn", type: "button", onclick: () => { live.status = "pending"; render(); runLive(true); } }, "Refresh now"));
  }
  const text = { pending: "Checking the live feed…",
    ok: `Live matching: feed from ${ago(live.feedTime)}, scored in your browser. ${live.added} role${live.added === 1 ? "" : "s"} added since the daily build (marked Live).`,
    error: `Live feed unavailable (${live.error}). Showing the daily build from ${ago(data.generated_at)}.` }[live.status];
  return h("div", { class: "panel small bar", style: "margin:10px 0 0;align-items:center" },
    h("span", { class: `badge ${live.status === "ok" ? "ok" : live.status === "error" ? "warn" : ""}` }, live.status === "ok" ? "Live" : live.status === "error" ? "Offline" : "…"), text,
    h("button", { class: "btn", type: "button", onclick: () => { live.status = "pending"; render(); runLive(true); } }, "Refresh now"));
}

function candidateHeader(c, back, sub) {
  const left = monthsLeft(c.visa?.expires);
  return h("div", {}, back, h("h1", {}, c.name || "Your matches"),
    c.headline ? h("p", { class: "muted", style: "margin:2px 0 0" }, c.headline) : null,
    h("ul", { class: "chips" },
      h("li", { class: `chip ${left != null && left < 6 ? "bad" : "warn"}` },
        `${c.visa?.label || "Visa not set"}${c.visa?.expires ? ` · until ${monthName(c.visa.expires)}${left != null ? ` (${left} months left)` : ""}` : ""}`),
      h("li", { class: "chip" }, ({ required: "Needs sponsorship", preferred: "Wants sponsorship before the visa ends", not_needed: "No sponsorship needed" })[c.visa?.sponsorship] || ""),
      h("li", { class: "chip ok" }, c.clearance?.held === "none" ? "No security clearance" : `Holds ${String(c.clearance?.held).toUpperCase()} clearance`),
      h("li", { class: "chip" }, c.driving_licence == null ? "Driving licence: not confirmed" : c.driving_licence ? "Holds a driving licence" : "No driving licence"),
      c.base_location ? h("li", { class: "chip" }, c.base_location) : null,
      (c.locations || []).length && !(c.locations.length === 1 && c.locations[0] === "GB")
        ? h("li", { class: "chip info" }, `Looking in: ${c.locations.map(k => (CandidateIntake.regions()[k] || {}).label || k).join(", ")}`) : null,
      c.english_only === false ? null : (c.locations || []).some(k => k !== "GB" && k !== "IE" && k !== "AU") ? h("li", { class: "chip" }, "English-language roles only") : null,
      c.experience_years ? h("li", { class: "chip" }, `${c.experience_years} yrs experience`) : null,
      c.education ? h("li", { class: "chip" }, c.education) : null),
    c.current_status ? h("p", { class: "small muted", style: "margin:6px 0 0" }, `Now: ${c.current_status}`) : null, sub);
}
let liveTimer = null;
let careerSite = () => "";           // company -> its careers site, from config/career_pages.json and config/employers.json
async function loadCareerLinks() {
  try {
    const [pages, employers] = await Promise.all([getJSON("../config/career_pages.json"), getJSON("../config/employers.json")]);
    careerSite = CandidateCareers.build(pages, employers);
  } catch (err) { /* the buttons simply fall back to the advert link */ }
}
function startLive() {
  clearInterval(liveTimer);
  render();
  runLive(false);
  liveTimer = setInterval(() => runLive(false), LIVE_RECHECK_MS);
}

// A recruiter's saved board: built daily, with live matching adding anything newer.
async function boardView(slug) {
  data = await getJSON(`data/${encodeURIComponent(slug)}.json`);
  document.title = `${data.candidate.name}: candidate board`;
  live.mode = "board"; live.baseJobs = data.jobs;
  Object.assign(state, { tab: "1", spons: "offered", source: "direct", country: "" });
  $header.replaceChildren(candidateHeader(data.candidate, h("a", { class: "back", href: "./#boards" }, "← Recruiter boards"),
    h("p", { class: "small muted" }, `Updated ${ago(data.generated_at)} · roles posted in the last ${data.window_days} days`)));
  startLive();
}

// A candidate's own results: the CV was scanned in this browser, and vacancies are matched live against the shared feed.
function selfView(profile) {
  const labels = CandidateIntake.labels();
  const c = { ...profile, also_consider: profile.also_consider.map(k => ({ key: k, label: labels[k].label, sponsorability: labels[k].sponsor })) };
  data = { candidate: c, jobs: [], sources: {}, window_days: profile.window_days || 7, generated_at: "" };
  document.title = "Your matching vacancies";
  live.mode = "self"; live.baseJobs = []; live.status = "pending"; live.firstPaint = true;
  Object.assign(state, { tab: "1", q: "", min: 0, sector: "", etier: "", source: "direct", country: "", spons: profile.visa?.sponsorship === "not_needed" ? "all" : "offered" });
  $header.replaceChildren(candidateHeader(c, h("a", { class: "back", href: "./", onclick: () => { window.__profile = null; try { sessionStorage.removeItem("cb_profile"); } catch (e) { /* private mode */ } } }, "← Change CV or details"),
    h("p", { class: "small muted" }, "Your CV was read in this browser only. Press Apply on a role to go to the employer's own advert.")));
  startLive();
}

function visible(j, tab = state.tab) {
  if (j.tier !== Number(tab)) return false;
  if (j.match < state.min) return false;
  if ((Date.now() - new Date(j.posted_at)) / 864e5 > state.days) return false;
  if (state.q && !`${j.title} ${j.company} ${j.location} ${j.role} ${j.sector}`.toLowerCase().includes(state.q.toLowerCase())) return false;
  if (state.sector && j.sector !== state.sector) return false;
  if (state.etier && String(j.employer_tier) !== state.etier) return false;
  if (!sourceOk(j)) return false;
  if (state.country && j.country !== state.country) return false;
  if (state.spons === "offered" && !j.sponsorship_offered) return false;
  if (state.spons === "not" && j.sponsorship_offered) return false;
  const blockers = j.hidden_by_default.filter(r => r !== "no_sponsorship");
  if (!state.showBlocked && blockers.length) return false;
  return true;
}

// Would this job show if only the source filter were lifted? (Used to say how many roles Adzuna-only filtering hides.)
function withSource(j, mode) { const keep = state.source; state.source = mode; const ok = visible(j); state.source = keep; return ok; }

function sortJobs(list) {
  const by = { match: (a, b) => b.match - a.match || a.sponsorship_rank - b.sponsorship_rank,
    newest: (a, b) => new Date(b.posted_at) - new Date(a.posted_at),
    sponsor: (a, b) => a.sponsorship_rank - b.sponsorship_rank || b.match - a.match,
    pay: (a, b) => (b.salary_annual || 0) - (a.salary_annual || 0) }[state.sort];
  return list.slice().sort(by);
}

function render() {
  const jobs = data.jobs;
  const counts = Object.fromEntries(["1", "2", "3", "4"].map(t => [t, jobs.filter(j => String(j.tier) === t && j.sponsorship_offered && !j.hidden_by_default.length && sourceOk(j)).length]));
  const sponsorOffered = jobs.filter(j => j.sponsorship === "confirmed" || j.sponsorship === "possible").length;
  const employers = new Set(jobs.filter(j => j.sponsorship_offered && sourceOk(j)).map(j => j.company)).size;
  const tabs = h("div", { class: "tabs", role: "tablist" }, TABS.map(([key, label]) =>
    h("button", { class: "tab", role: "tab", "aria-selected": String(state.tab === key), onclick: () => { state.tab = key; render(); } },
      label, counts[key] != null ? h("span", { class: "n" }, counts[key]) : null)));
  const parts = [
    h("div", { class: "stats" },
      h("div", { class: "stat" }, h("b", {}, counts[1] + counts[2] + counts[3]), "ready to send (tiers 1–3)"),
      h("div", { class: "stat" }, h("b", {}, sponsorOffered), "advert offers sponsorship"),
      h("div", { class: "stat" }, h("b", {}, employers), "sponsor-licensed employers"),
      h("div", { class: "stat" }, h("b", {}, jobs.filter(j => j.hidden_by_default.includes("clearance")).length), "need clearance (hidden)")),
    liveBanner(), live.mode === "self" ? rolesPanel() : null, sourceStatus(), tabs];
  if (state.tab === "employers") parts.push(employersView());
  else if (state.tab === "cv") parts.push(cvView());
  else parts.push(...jobsView());
  $app.replaceChildren(...parts.flat().filter(Boolean));
}

const FEED_SOURCE_NAMES = { adzuna: "Adzuna", reed: "Reed", nhs_jobs: "NHS Jobs", teaching_vacancies: "Teaching Vacancies (schools)", jobs_ac_uk: "jobs.ac.uk (universities)",
  the_unijobs: "THE unijobs (universities)", career_sites: "Employer career sites", public_sector_employers: "Civil Service departments and councils (via Reed)",
  rss: "Council RSS feeds", arbeitnow: "Arbeitnow", jobtech_sweden: "Platsbanken (Sweden)", euraxess: "EURAXESS" };
// The roles the candidate asked for: add or remove them here and the matching runs again, without re-uploading the CV.
function saveProfile() {
  const { also_consider, ...rest } = data.candidate;
  const profile = { ...rest, also_consider: also_consider.map(f => f.key || f) };
  window.__profile = profile;
  try { sessionStorage.setItem("cb_profile", JSON.stringify(profile)); } catch (e) { /* private mode */ }
}
function rematch() { saveProfile(); state.tab = "1"; live.status = "pending"; render(); runLive(true); }
function rolesPanel() {
  const mine = data.candidate.roles.filter(r => r.source === "added by candidate");
  const input = h("input", { list: "role-suggestions-results", placeholder: "Add a role, e.g. Data Analyst", style: "min-width:260px;flex:1" });
  const add = () => { if (CandidateIntake.addRoles(data.candidate, input.value.split(/[,\n;]/)).length) rematch(); else input.value = ""; };
  input.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); add(); } });
  return h("div", { class: "panel small" }, h("b", {}, "Roles you want: "),
    ...mine.map(r => h("span", { class: "chip info", style: "margin-right:6px" }, r.title, " ", h("button", { type: "button", class: "btn", style: "padding:0 6px", "aria-label": `Remove ${r.title}`,
      onclick: () => { data.candidate.roles = data.candidate.roles.filter(x => x !== r); rematch(); } }, "×"))),
    mine.length ? null : h("span", { class: "muted" }, "none yet. "),
    h("div", { class: "bar", style: "margin-top:6px" }, input, h("button", { type: "button", class: "btn", onclick: add }, "Add role")),
    h("datalist", { id: "role-suggestions-results" }, ...CandidateIntake.suggestions().map(t => h("option", { value: t }))),
    h("p", { class: "muted", style: "margin:6px 0 0" }, "Roles you add are searched first and show under Tier 1. They only appear if employers advertise them this week, and the match % reflects how much of your CV fits."));
}

function sourceStatus() {
  const bad = Object.entries(data.sources).filter(([, s]) => s.status !== "ok");
  const feed = Object.entries(data.feedSources || {}).filter(([k]) => FEED_SOURCE_NAMES[k] && k !== "arbeitnow" && k !== "jobtech_sweden" && k !== "euraxess");
  if (!bad.length && !feed.length) return h("span");
  const note = s => (s.status === "ok" || s.status === "partial" ? `${s.count ?? 0} adverts read${s.employers_ok != null ? ` from ${s.employers_ok} employers` : ""}` : `${s.status}${s.reason || s.error ? `: ${s.reason || s.error}` : ""}`);
  const failedSites = (data.feedSources?.career_sites?.employers_failed) || [];
  return h("details", { class: "panel small" }, h("summary", {}, bad.length ? `Data sources: ${bad.length} not read this run` : "Where these vacancies come from"),
    bad.length ? h("ul", {}, bad.map(([n, s]) => h("li", {}, `${n}: ${s.status} ${s.reason || s.error || ""}`))) : null,
    feed.length ? h("table", {}, h("thead", {}, h("tr", {}, ["Shared feed source", "Last feed run"].map(t => h("th", {}, t)))),
      h("tbody", {}, feed.map(([k, st]) => h("tr", {}, h("td", {}, FEED_SOURCE_NAMES[k]), h("td", { class: st.status === "ok" ? "" : "muted" }, note(st)))))) : null,
    failedSites.length ? h("p", { class: "small" }, h("b", {}, `Career sites that could not be read (${failedSites.length}): `), failedSites.join("; ")) : null,
    h("p", { class: "muted" }, "Roles from sources that were not read are missing, so the list is a floor, not the whole market. “Skipped” usually means an API key is not set."));
}

function jobsView() {
  const inTab = data.jobs.filter(j => String(j.tier) === state.tab);
  const sectors = [...new Set(inTab.map(j => j.sector).filter(Boolean))].sort();
  const keepCountry = state.country; state.country = "";           // counts per country under every other filter
  const tally = {};
  for (const j of data.jobs.filter(j => visible(j))) tally[j.country] = (tally[j.country] || 0) + 1;
  state.country = keepCountry;
  const offered = new Set([...(data.candidate.countries || []).filter(c => data.jobs.some(j => j.country === c)), ...Object.keys(tally)]);
  const countries = [...offered].map(c => [c, tally[c] || 0]).sort((a, b) => b[1] - a[1] || countryName(a[0]).localeCompare(countryName(b[0])));
  const showCountry = (data.candidate.countries || []).length > 1 || countries.length > 1;
  const sel = (name, opts, cur, fn) => h("select", { name, onchange: e => { fn(e.target.value); render(); } },
    opts.map(([v, l]) => h("option", { value: v, ...(String(v) === String(cur) ? { selected: true } : {}) }, l)));
  const bar = h("div", { class: "panel bar" },
    h("label", {}, "Search (press Enter)", h("input", { type: "search", value: state.q, placeholder: "Role, employer, city…", onchange: e => { state.q = e.target.value; render(); } })),
    h("label", {}, "Sponsorship", sel("spons", [["offered", "Offered / licensed sponsor"], ["all", "All"], ["not", "Not offered"]], state.spons, v => state.spons = v)),
    h("label", {}, "Posted within", sel("days", [[7, "7 days"], [3, "3 days"], [1, "24 hours"]], state.days, v => state.days = Number(v))),
    h("label", {}, "Min match", sel("min", [[0, "Any"], [50, "50%+"], [60, "60%+"], [70, "70%+"]], state.min, v => state.min = Number(v))),
    h("label", {}, "Sector", sel("sector", [["", "All"], ...sectors.map(s => [s, s])], state.sector, v => state.sector = v)),
    h("label", {}, "Employer tier", sel("etier", [["", "All"], ["1", "Tier 1"], ["2", "Tier 2"], ["3", "Tier 3"]], state.etier, v => state.etier = v)),
    showCountry ? h("label", {}, "Country", sel("country", [["", "All countries"], ...countries.map(([c, n]) => [c, `${countryName(c)} (${n})`])], state.country, v => state.country = v)) : null,
    h("label", {}, "Where advertised", sel("source", SOURCE_FILTERS, state.source, v => state.source = v)),
    h("label", {}, "Sort", sel("sort", [["match", "Best match"], ["sponsor", "Sponsorship first"], ["newest", "Newest"], ["pay", "Highest pay"]], state.sort, v => state.sort = v)),
    h("label", { class: "check" }, h("input", { type: "checkbox", ...(state.showBlocked ? { checked: true } : {}), onchange: e => { state.showBlocked = e.target.checked; render(); } }), "Show roles needing clearance, below visa pay, in another language, reserved for nationals, or without a Skilled Worker licence"),
    h("button", { class: "btn", onclick: () => exportCsv(sortJobs(data.jobs.filter(j => visible(j)))) }, "Export CSV"));
  const list = sortJobs(data.jobs.filter(j => visible(j)));
  const note = state.tab === "4" ? h("p", { class: "small muted" }, "Other roles at employers that can sponsor, using the same skills on a different route. Many of these (admin, IT support) are below the Skilled Worker skill level, so ask the employer first.") : null;
  const hiddenByAdzuna = state.source === "all" ? 0 : data.jobs.filter(j => !sourceOk(j) && withSource(j, "all")).length;
  return [bar, note, h("p", { class: "small muted" }, `${plural(list.length, "role")} shown`,
      hiddenByAdzuna ? ` · ${hiddenByAdzuna} more only on job boards (change “Where advertised” to see them)` : ""),
    list.length ? h("ul", { class: "cards" }, list.slice(0, 250).map(card)) : h("p", { class: "empty" }, state.country ? `No roles in ${countryName(state.country)} match these filters right now. Roles abroad are fewer: try “Where advertised” or “Sponsorship”, and see “Where these vacancies come from” for what the feed covers.` : "No roles match these filters.")];
}

// Adzuna links open through an Adzuna page that does not load everywhere (for example in India), so for those adverts the
// employer's own careers site leads and the Adzuna link is the fallback. Elsewhere the advert link leads.
function applyRow(j) {
  const site = j.employer_site || careerSite(j.company);
  const viaAdzuna = j.source === "Adzuna";
  const link = (href, text, primary, title) => h("a", { class: `btn${primary ? " primary" : ""}`, href, target: "_blank", rel: "noopener noreferrer", title }, text);
  const detail = h("p", { class: "small" }, h("b", {}, j.cv_to_use ? `Send: ${j.track} CV` : "Send: best-fitting CV"), ` · target role: ${j.role}${j.family_label ? ` (${j.family_label})` : ""}`);
  if (viaAdzuna && site) {
    return h("div", {}, h("div", { class: "apply-row" }, link(site, "Employer careers site →", true, "The employer's own careers site"),
      link(j.url, "Advert on Adzuna", false, "Adzuna's page for this advert; it does not open everywhere"), detail),
      h("p", { class: "small muted", style: "margin:4px 0 0" }, `On the careers site, search for “${j.title}”${j.location ? ` in ${j.location}` : ""}.`));
  }
  return h("div", { class: "apply-row" }, link(j.url, viaAdzuna ? "Apply on Adzuna →" : "Apply →", true),
    site && site !== j.url ? link(site, "Employer careers page", false, "The employer's own careers site, if the Apply link does not open") : null, detail);
}

function card(j) {
  const sp = j.sponsorship_offered ? (j.sponsorship === "licensed_sponsor" ? "info" : "ok") : "bad";
  const cl = j.clearance, lic = j.driving_licence, pay = j.visa_pay;
  const badges = [
    badge(j.sponsorship_label, sp),
    badge(cl.level === "none" ? cl.label : cl.label, cl.blocks ? "bad" : cl.level === "none" ? "" : "ok", cl.quote),
    lic.need ? badge(`Driving licence ${lic.need}${lic.status === "unknown" ? " (candidate: not confirmed)" : lic.status === "missing" ? ": candidate has none" : ""}`, lic.status === "missing" && lic.need === "required" ? "bad" : "warn", lic.quote) : null,
    pay.status ? badge({ meets: "Pay meets visa minimum", partial: "Pay partly meets visa minimum", below: "Pay below visa minimum", unstated: "Pay not stated" }[pay.status], pay.status === "below" ? "bad" : pay.status === "unstated" ? "" : "ok", pay.note) : null,
    j.sponsorability === "rare" ? badge("Sponsorship unlikely at this level", "warn", j.sponsorability_note) : j.sponsorability === "check" ? badge("Ask if role can be sponsored", "", j.sponsorability_note) : null,
    j.work_mode ? badge(j.work_mode === "remote" ? "Remote" : "Hybrid") : null,
    !ENGLISH_COUNTRIES.includes(j.country) ? badge(j.english === false ? "Needs another language" : "English-language role", j.english === false ? "bad" : "ok") : null,
    !["GB", "IE"].includes(j.country) && pay.status === "" && data.candidate.visa?.sponsorship !== "not_needed" ? badge("Pay vs visa minimum not checked here", "", "Salary thresholds are only checked for the UK and Ireland") : null,
    j.sector ? badge(j.sector) : null, j.employer_tier ? badge(`Employer tier ${j.employer_tier}`) : null,
    badge(j.source + (j.channel === "career_site" ? " · employer site" : "")),
    j.live ? badge("Live", "info", "Found by matching the latest feed in your browser; not in the daily build yet") : null,
    ...j.flags.map(f => badge(f, "warn"))];
  return h("li", { class: `card ${j.hidden_by_default.length ? "dim" : ""}`, "data-tier": j.tier },
    h("div", { class: "card-top" },
      h("div", {}, h("h3", {}, h("a", { href: j.url, target: "_blank", rel: "noopener" }, j.title)),
        h("p", { class: "meta" }, [j.company, j.location, j.country !== "GB" ? countryName(j.country) : "", money(j.salary, j.country), `posted ${ago(j.posted_at)}`].filter(Boolean).join(" · "))),
      h("div", { class: "match", title: "Fit with the candidate's CV: title 50 · skills 40 · level 10" }, h("b", {}, `${j.match}%`), "match",
        h("div", { class: "meter" }, h("i", { style: `width:${j.match}%` })))),
    h("ul", { class: "badges" }, badges.filter(Boolean).map(b => h("li", {}, b))),
    applyRow(j),
    h("details", { class: "why" }, h("summary", {}, "Why this score and these labels"),
      h("ul", {}, j.reasons.map(r => h("li", {}, r)),
        j.skills_matched.length ? h("li", {}, `CV skills in the advert: ${j.skills_matched.join(", ")}`) : null,
        j.evidence === "extract" ? h("li", { class: "muted" }, "Based on the advert extract the feed keeps. Open the advert to confirm duties, clearance and sponsorship before sending.") : null,
        j.sponsorship_evidence ? h("li", {}, "Sponsorship: ", h("span", { class: "quote" }, `“${j.sponsorship_evidence}”`)) : null,
        j.sponsor_routes?.length ? h("li", {}, `${j.sponsor_register || "Register"} routes: ${j.sponsor_routes.join(", ")}`) : null,
        cl.quote ? h("li", {}, "Clearance: ", h("span", { class: "quote" }, `“${cl.quote}”`)) : null,
        pay.note ? h("li", {}, pay.note) : null,
        j.sponsorability_note ? h("li", {}, j.sponsorability_note) : null,
        j.hidden_by_default.length ? h("li", {}, `Hidden by default: ${j.hidden_by_default.join(", ").replaceAll("_", " ")}`) : null)));
}

function employersView() {
  const by = new Map();
  for (const j of data.jobs.filter(j => j.sponsorship_offered && sourceOk(j))) {
    const e = by.get(j.company) || { company: j.company, jobs: [], routes: j.sponsor_routes || [], reg: j.sponsor_register };
    e.jobs.push(j); by.set(j.company, e);
  }
  const rows = [...by.values()].sort((a, b) => b.jobs.length - a.jobs.length || b.jobs[0].match - a.jobs[0].match);
  return h("div", { class: "panel" }, h("h2", {}, `${rows.length} employers that can sponsor, with roles for this candidate`),
    h("p", { class: "small muted" }, "Employers with an advert that offers sponsorship, or on the Home Office register of licensed sponsors. Tier 4 shows their other roles worth a look."),
    h("table", {}, h("thead", {}, h("tr", {}, ["Employer", "Roles", "Best fit", "Licence routes"].map(t => h("th", {}, t)))),
      h("tbody", {}, rows.slice(0, 200).map(e => h("tr", {},
        h("td", {}, e.company), h("td", {}, e.jobs.sort((a, b) => b.match - a.match).slice(0, 4).map(j => h("div", {}, h("a", { href: j.url, target: "_blank", rel: "noopener" }, j.title), h("span", { class: "muted small" }, ` · tier ${j.tier} · ${j.match}%`))), e.jobs.length > 4 ? h("div", { class: "muted small" }, `+${e.jobs.length - 4} more`) : null),
        h("td", {}, `${Math.max(...e.jobs.map(j => j.match))}%`),
        h("td", { class: "small" }, (e.routes || []).join(", ") || (e.reg || "Advert offers sponsorship")))))));
}

function cvView() {
  const c = data.candidate;
  const tierNames = { 1: "Tier 1 · Core roles (apply first)", 2: "Tier 2 · Close to the CV", 3: "Tier 3 · Stretch / new direction" };
  const byTier = t => c.roles.filter(r => r.tier === t);
  return h("div", {},
    h("div", { class: "grid2" }, [1, 2, 3].map(t => h("div", { class: "panel" }, h("h2", {}, tierNames[t]),
      byTier(t).length ? h("ul", { class: "small" }, byTier(t).map(r => h("li", {}, r.title, h("span", { class: "muted" }, ` · ${r.track} CV${r.source !== "recruiter list" ? " · suggested from CV" : ""}`)))) : h("p", { class: "muted small" }, "None")))),
    h("div", { class: "panel" }, h("h2", {}, "Other roles worth a look"),
      h("p", { class: "small muted" }, "Families the CV also supports. Shown at employers that can sponsor (tab “Other roles”)."),
      h("ul", { class: "chips" }, c.also_consider.map(f => h("li", { class: `chip ${f.sponsorability === "rare" ? "warn" : ""}`, title: f.sponsorability === "rare" ? "Usually below the Skilled Worker skill level" : "" }, f.label)))),
    h("div", { class: "panel" }, h("h2", {}, "CVs scanned and skills used for matching"),
      c.tracks.map(t => h("div", {}, h("h3", {}, `${t.name} CV`, h("span", { class: "muted small" }, ` · ${t.cv || ""}`)),
        h("ul", { class: "chips" }, t.skills.map(s => h("li", { class: "chip" }, s.replace(/\[sz\]/g, "s").replace(/[\\?]/g, "")))))),
      c.notes ? h("p", { class: "small muted" }, c.notes) : null,
      h("p", { class: "small muted" }, "Recruiters: ", h("button", { class: "btn", type: "button", onclick: downloadProfile }, "Download profile (JSON)"),
        " to save this candidate as a recruiter board (candidates/profiles/<name>.json).")));
}
function downloadProfile() {
  const { also_consider, ...rest } = data.candidate;
  const profile = { ...rest, also_consider: also_consider.map(f => f.key || f) };
  const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(profile, null, 1) + "\n"], { type: "application/json" })), download: `${profile.slug || "candidate"}.json` });
  document.body.append(a); a.click(); a.remove();
}

function exportCsv(list) {
  const cols = ["tier", "match", "title", "company", "location", "salary", "posted_at", "sponsorship_label", "clearance", "visa_pay", "role", "track", "source", "url", "careers_site"];
  const cell = v => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const val = (j, k) => k === "clearance" ? j.clearance.label : k === "visa_pay" ? j.visa_pay.status : k === "salary" ? money(j.salary) : k === "careers_site" ? (j.employer_site || careerSite(j.company)) : j[k];
  const csv = [cols.join(","), ...list.map(j => cols.map(k => cell(val(j, k))).join(","))].join("\n");
  const a = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: `${data.candidate.slug}-roles.csv` });
  document.body.append(a); a.click(); a.remove();
}

// ------------------------------------------------------------------------------------------ routing
// One link: /candidates/ is the form, #results the candidate's matches, #boards the recruiter list, ?c=<slug> a saved board.
function formView() {
  document.title = "Find roles for your CV";
  $header.replaceChildren(h("div", {}, h("h1", {}, "Find roles for your CV"),
    h("p", { class: "muted small", style: "margin:4px 0 0" }, "Upload your CV, answer a few questions, and see vacancies from the last 7 days that fit you, with a link to apply. Your CV stays in your browser.")));
  $app.replaceChildren(document.getElementById("add-tpl").content.cloneNode(true));
  clearInterval(liveTimer);
  mountAdd(h, profile => {
    try { sessionStorage.setItem("cb_profile", JSON.stringify(profile)); } catch (e) { /* private mode: results still show once */ }
    window.__profile = profile;
    location.hash = "#results";
  });
}
async function ensureTaxonomy() { CandidateIntake.init(await getJSON("../candidateboard/roles.json"), await getJSON("../candidateboard/regions.json")); }

async function route() {
  try {
    const slug = new URLSearchParams(location.search).get("c");
    if (slug) { await ensureTaxonomy(); await boardView(slug); }
    else if (location.hash === "#boards") { clearInterval(liveTimer); await listView(); }
    else if (location.hash === "#results") {
      let profile = window.__profile;
      try { profile = profile || JSON.parse(sessionStorage.getItem("cb_profile")); } catch (e) { profile = null; }
      if (!profile) { location.hash = ""; return; }
      await ensureTaxonomy(); selfView(profile);
    } else formView();
  } catch (err) {
    $app.replaceChildren(h("p", { class: "empty" }, `Could not load this page: ${err.message}`));
  }
}
window.addEventListener("hashchange", () => { if (!new URLSearchParams(location.search).get("c")) route(); });
route();
