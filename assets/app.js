const DATA_URL = "data/jobs.json";
const TIERS_URL = "config/company_tiers.json";
const PAGE_SIZE = 40;
const DAY_MS = 86_400_000;

const SIZES = ["large", "medium", "small", "unknown"];
const CHANNELS = {
  career_site: "Employer's own careers site",
  official: "NHS, university, school & government boards",
  aggregator: "Job boards (reposted adverts)",
};
// Direct applications are shown by default; reposted job-board adverts are opt-in.
const DEFAULT_CHANNELS = new Set(["career_site", "official"]);
const COUNTRY_NAMES = new Intl.DisplayNames(["en"], { type: "region" });
// Filter values that are regions rather than ISO countries.
const REGION_OPTIONS = {
  "GB-SCT": { label: "Scotland (UK)", flag: "GB", test: (j) => j.country === "GB" && j.region === "Scotland" },
  "AE-DXB": { label: "Dubai (UAE)", flag: "AE", test: (j) => j.country === "AE" && j.region === "Dubai" },
  EU: { label: "Europe (excl. UK)", flag: "EU", test: (j) => !["GB", "US", "AE"].includes(j.country) },
};
const DEFAULT_FEATURED = ["GB", "GB-SCT", "IE", "US", "NL", "LU", "SE", "FI", "PL", "ES", "AE", "AE-DXB"];
const PUBLIC_SECTORS = new Set(["Public Sector & Government", "NHS & Healthcare", "Charity & Non-profit"]);
// Quick views across the top; each narrows the filtered list further (the directory replaces it).
const VIEWS = {
  all: { label: "All jobs", test: () => true },
  university: { label: "Universities & research", test: (j) => j.sector === "University & Research Institute" },
  school: { label: "Schools & colleges", test: (j) => j.sector === "School & College" },
  public: { label: "Public sector & NHS", test: (j) => PUBLIC_SECTORS.has(j.sector) },
  aviation: { label: "Aviation & operations", test: (j) => !!j.aviation },
  early: { label: "PSW & OPT friendly", test: (j) => !!j.early_career },
  directory: { label: "PSW & OPT employers", test: () => true },
};
const ENGLISH_COUNTRIES = new Set(["GB", "IE", "US", "MT"]);
// Feeds written before jobs carried a region: recognise the main Scottish places.
const SCOTLAND_RE = /\b(scotland|scottish|glasgow|edinburgh|aberdeen|dundee|inverness|stirling|st andrews|paisley|fife|lothian|lanarkshire|ayrshire|perth|nhs (lothian|grampian|tayside|highland))\b/i;
const $ = (sel) => document.querySelector(sel);

const state = { data: null, jobs: [], filtered: [], shown: PAGE_SIZE, view: "all" };

// ------------------------------------------------------------------ helpers
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : "#";
  } catch { return "#"; }
}

function ago(date) {
  const hours = Math.floor((Date.now() - date) / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

function countryName(code) {
  try { return COUNTRY_NAMES.of(code); } catch { return code; }
}

const flag = (code) => code && code.length === 2
  ? String.fromCodePoint(...[...code.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0)))
  : "";

function checkboxes(container, name, values, labelFn = (v) => v, defaults = null) {
  const el = $(container);
  for (const v of values) {
    const label = document.createElement("label");
    const on = !defaults || defaults.has(v) ? "checked" : "";
    label.innerHTML = `<input type="checkbox" name="${name}" value="${esc(v)}" ${on}> ${esc(labelFn(v))} <span class="count" data-count="${name}:${esc(v)}"></span>`;
    el.append(label);
  }
}

// ------------------------------------------------------------------ filters
function readFilters() {
  const form = new FormData($("#filters"));
  return {
    q: (form.get("q") || "").trim().toLowerCase(),
    country: form.get("country") || "",
    days: Number(form.get("days") || 7),
    sponsorship: new Set(form.getAll("sponsorship")),
    hasContact: form.get("hasContact") === "1",
    english: form.get("english") === "1",
    early: form.get("early") === "1",
    hideLow: form.get("hideLow") === "1",
    aviation: form.get("aviation") || "",
    role: new Set(form.getAll("role")),
    channel: new Set(form.getAll("channel")),
    tier: new Set(form.getAll("tier")),
    size: new Set(form.getAll("size")),
    sector: new Set(form.getAll("sector")),
    domain: new Set(form.getAll("domain")),
  };
}

function matchesCountry(job, country) {
  if (!country) return true;
  const region = REGION_OPTIONS[country];
  return region ? region.test(job) : job.country === country;
}

function matches(job, f, view = state.view) {
  if (Date.now() - job._posted > f.days * DAY_MS) return false;
  if (!matchesCountry(job, f.country)) return false;
  if (!VIEWS[view].test(job)) return false;
  if (f.english && !job.english) return false;
  if (f.early && !job.early_career) return false;
  if (f.hideLow && job.low_sponsorship) return false;
  if (f.aviation === "any" && !job.aviation) return false;
  if (f.aviation && f.aviation !== "any" && job.aviation !== f.aviation) return false;
  if (!f.role.has(job.role)) return false;
  if (!f.sponsorship.has(job.sponsorship)) return false;
  if (!f.channel.has(job.channel)) return false;
  if (f.hasContact && !job.contacts.length) return false;
  if (!f.tier.has(String(job.tier))) return false;
  if (!f.size.has(job.size)) return false;
  if (!f.sector.has(job.sector)) return false;
  if (!f.domain.has(job.domain)) return false;
  if (f.q && !job._haystack.includes(f.q)) return false;
  return true;
}

const SORTS = {
  newest: (a, b) => b._posted - a._posted,
  tier: (a, b) => a.tier - b.tier || b._posted - a._posted,
  contact: (a, b) => (b.contacts.length > 0) - (a.contacts.length > 0) || b._posted - a._posted,
};

function apply() {
  const f = readFilters();
  state.filtered = state.jobs.filter((j) => matches(j, f)).sort(SORTS[$("#sort").value]);
  renderViews(f);
  state.shown = PAGE_SIZE;
  syncUrl();
  render();
}

// ------------------------------------------------------------------ rendering
function renderStats() {
  const jobs = state.filtered;
  const employers = new Set(jobs.map((j) => j.company.toLowerCase())).size;
  const tiles = [
    ["Open roles", jobs.length],
    ["Hiring employers", employers],
    ["Sponsorship stated", jobs.filter((j) => j.sponsorship === "confirmed").length],
    ["With hiring contact", jobs.filter((j) => j.contacts.length).length],
    ["PSW / OPT friendly", jobs.filter((j) => j.early_career).length],
    ["Countries", new Set(jobs.map((j) => j.country)).size],
  ];
  $("#stats").innerHTML = tiles.map(([k, v]) =>
    `<div class="stat"><span class="stat-value">${esc(v)}</span><span class="stat-label">${esc(k)}</span></div>`).join("");

  // Per-option counts within the current window, so empty options are obvious.
  const f = readFilters();
  const inWindow = state.jobs.filter((j) => Date.now() - j._posted <= f.days * DAY_MS);
  for (const el of document.querySelectorAll("[data-count]")) {
    const [key, value] = el.dataset.count.split(":");
    el.textContent = inWindow.filter((j) => String(j[key]) === value).length;
  }
}

function contactHtml(c) {
  const badge = c.provenance === "verified"
    ? `<a class="tag ok" href="${esc(safeUrl(c.source_url))}" target="_blank" rel="noopener" title="Verified ${esc(c.verified_on)}">verified</a>`
    : `<span class="tag" title="Published with the job advert">from advert</span>`;
  const who = c.name
    ? `<strong>${esc(c.name)}</strong>${c.role ? `, <span class="muted">${esc(c.role)}</span>` : ""}`
    : `<span class="muted">${esc(c.role || c.type)}</span>`;
  const email = c.email ? `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : "";
  const phone = c.phone ? `<a href="tel:${esc(c.phone.replace(/[^\d+]/g, ""))}">${esc(c.phone)}</a>` : "";
  return `<li>${who} ${badge}<br>${[email, phone].filter(Boolean).join(" · ")}</li>`;
}

function earlyTag(j) {
  if (!j.early_career) return "";
  const route = j.country === "US" ? "OPT" : "PSW";
  return j.early_career === "stated"
    ? `<span class="tag ok" title="The advert says it accepts ${route === "OPT" ? "OPT / STEM OPT" : "Graduate visa"} holders">${route} welcome</span>`
    : `<span class="tag direct" title="Entry-level role at an employer that sponsors">${route} friendly</span>`;
}

function jobHtml(j) {
  const sponsorTag = {
    confirmed: `<span class="tag ok" title="The advert states visa sponsorship is available">Sponsorship offered</span>`,
    licensed_sponsor: `<span class="tag warn" title="Employer is on the official sponsor register but the advert does not mention sponsorship — ask before applying">${j.sponsor_register === "US H-1B" ? "H-1B sponsor" : "Licensed sponsor"}</span>`,
    employer_visa: `<span class="tag ok" title="UAE employers sponsor every foreign hire's residence and work visa">Employer visa (UAE)</span>`,
    graduate_route: `<span class="tag warn" title="No sponsorship, but Graduate visa (PSW) / OPT holders are welcome">No sponsorship · ${j.country === "US" ? "OPT" : "Graduate visa"} OK</span>`,
  }[j.sponsorship] || "";
  const englishTag = j.english && !ENGLISH_COUNTRIES.has(j.country)
    ? `<span class="tag direct" title="Advert in English, no other language required">English-speaking</span>` : "";
  const channelTag = {
    career_site: `<span class="tag direct" title="Advert taken from the employer's own careers site">Employer careers site</span>`,
    official: `<span class="tag direct" title="Official public-sector / academic job board">${esc(j.source)}</span>`,
    aggregator: `<span class="tag" title="Reposted by a job board; the employer's own advert may differ">via ${esc(j.source)}</span>`,
  }[j.channel] || "";
  const applyLabel = j.channel === "career_site" ? "Apply on employer site"
    : j.channel === "official" ? `Apply on ${j.source}` : "View advert";
  const register = j.sponsor_register
    ? `<span class="tag" title="${esc(j.sponsor_routes.join(", "))}">${esc(j.sponsor_register)} register</span>` : "";
  const people = (words) => `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(`${j.company} ${words}`)}`;
  const manager = people(`${j.role && j.role !== "Other" ? j.role : j.domain} manager`);
  const recruiter = people("talent acquisition OR recruiter");
  const search = `<a href="${esc(manager)}" target="_blank" rel="noopener">find the hiring manager</a> or
    <a href="${esc(recruiter)}" target="_blank" rel="noopener">recruiter</a> on LinkedIn`;
  const contacts = j.contacts.length
    ? `<ul class="contacts">${j.contacts.map(contactHtml).join("")}</ul><p class="muted small">Or ${search}.</p>`
    : `<p class="muted small">No hiring contact published. Apply via the advert, or ${search}.</p>`;

  return `<li class="job">
    <div class="job-head">
      <h2><a href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener">${esc(j.title)}</a></h2>
      <span class="posted" title="${esc(j._posted.toLocaleString())}">${ago(j._posted)}</span>
    </div>
    <p class="employer"><strong>${esc(j.company || "Employer not stated")}</strong>
      <span class="tier t${j.tier}">Tier ${j.tier}</span>
      <span class="muted">${esc(j.size === "unknown" ? "size unknown" : j.size)}</span></p>
    <p class="meta">${flag(j.country)} ${esc(j.location || countryName(j.country))}${j.region && !(j.location || "").includes(j.region) ? ` · ${esc(j.region)}` : ""}
      ${j.salary ? ` · ${esc(j.salary)}` : ""}${j.contract ? ` · ${esc(j.contract)}` : ""}</p>
    <p class="tags">${channelTag}${sponsorTag}${earlyTag(j)}${englishTag}${register}${j.aviation ? `<span class="tag direct" title="Aviation &amp; operations job family">✈ ${esc(j.aviation)}</span>` : ""}${j.low_sponsorship ? `<span class="tag warn" title="Front-line role that rarely meets sponsorship skill and salary levels">Rarely sponsored</span>` : ""}<span class="tag">${esc(j.role !== "Other" ? j.role : j.domain)}</span><span class="tag">${esc(j.sector)}</span></p>
    ${j.description ? `<p class="desc">${esc(j.description)}</p>` : ""}
    <div class="job-foot">
      <div class="contact-block"><h3>Hiring contact</h3>${contacts}</div>
      <a class="btn" href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener">${esc(applyLabel)}</a>
    </div>
  </li>`;
}

function renderViews(f) {
  const counts = Object.fromEntries(Object.keys(VIEWS).map((v) =>
    [v, v === "directory" ? directoryRows(f).length : state.jobs.filter((j) => matches(j, f, v)).length]));
  $("#views").innerHTML = Object.entries(VIEWS).map(([v, { label }]) =>
    `<button type="button" class="view${v === state.view ? " active" : ""}" data-view="${v}" aria-pressed="${v === state.view}">
      ${esc(label)} <span class="count">${counts[v]}</span></button>`).join("");
  const active = $("#views .active");
  if (active) $("#views").scrollLeft = active.offsetLeft - $("#views").offsetLeft - 16;
}

// ------------------------------------------------------------------ PSW / OPT employer directory
function directoryRows(f) {
  return (state.data?.employers || []).filter((e) =>
    matchesCountry(e, f.country)
    && f.tier.has(String(e.tier)) && f.size.has(e.size)
    && (!f.q || `${e.name} ${e.programme} ${e.sector}`.toLowerCase().includes(f.q)));
}

function renderDirectory() {
  const rows = directoryRows(readFilters());
  const head = `<tr><th>Employer</th><th>Route</th><th>Size · tier</th><th>Sponsor record</th><th>Open roles</th><th>Find jobs</th></tr>`;
  const body = rows.map((e) => {
    const route = e.route === "OPT" ? "US OPT / STEM OPT" : "UK Graduate visa (PSW)";
    const record = e.on_register
      ? `<span class="tag ok">${esc(e.register === "US H-1B" ? "Files H-1Bs" : "Licensed sponsor")}</span>`
      : e.register_checked === false
        ? `<span class="tag" title="The official register could not be downloaded on this run">Not checked</span>`
        : `<span class="tag warn" title="Not matched by name on the register: check the employer's legal name">Not matched</span>`;
    const q = encodeURIComponent(`${e.name} ${e.route === "OPT" ? "new grad" : "graduate scheme"}`);
    const links = [
      e.careers_url ? `<a href="${esc(safeUrl(e.careers_url))}" target="_blank" rel="noopener">Careers</a>` : "",
      `<a href="https://www.linkedin.com/jobs/search/?keywords=${q}&f_E=1%2C2" target="_blank" rel="noopener">LinkedIn</a>`,
      `<a href="https://www.google.com/search?q=${q}" target="_blank" rel="noopener">Web</a>`,
    ].filter(Boolean).join(" · ");
    const roles = e.open_roles
      ? `<button type="button" class="linkish" data-employer="${esc(e.name)}">${e.open_roles}${e.early_career_roles ? ` (${e.early_career_roles} entry-level)` : ""}</button>`
      : "0";
    return `<tr><td><strong>${esc(e.name)}</strong> ${flag(e.country)}<br><span class="muted small">${esc(e.programme || e.sector)}${e.curated ? "" : " · found in feed"}</span></td>
      <td>${esc(route)}</td><td>${esc(e.size)} · Tier ${esc(e.tier)}</td><td>${record}</td><td>${roles}</td><td>${links}</td></tr>`;
  });
  $("#employers").innerHTML = head + (body.join("") || `<tr><td colspan="6">No employers match these filters.</td></tr>`);
  $("#summary").textContent = `${rows.length} employers`;
}

function render() {
  const directory = state.view === "directory";
  $("#directory").hidden = !directory;
  $("#jobs").hidden = directory;
  $(".toolbar label").hidden = directory;
  if (directory) {
    $("#more").hidden = true;
    $("#notice").hidden = true;
    renderStats();
    renderDirectory();
    return;
  }
  renderStats();
  const { filtered, shown } = state;
  $("#summary").textContent = `${filtered.length} of ${state.jobs.length} roles match`;
  $("#jobs").innerHTML = filtered.slice(0, shown).map(jobHtml).join("");
  $("#more").hidden = filtered.length <= shown;

  if (!state.jobs.length) {
    showNotice(`No jobs in the feed yet. Run the <strong>Refresh sponsored jobs</strong> workflow in the repository's
      Actions tab (and add the optional API keys described in the README) to populate it.`);
  } else if (!filtered.length) {
    const hidden = hiddenBy();
    if (hidden.length) {
      const total = Math.max(...hidden.map((h) => h.count));
      showNotice(`${total} ${total === 1 ? "job is" : "jobs are"} hidden by your filters: ${hidden.map((h) =>
        `<strong>${esc(h.label)}</strong> (${h.count})`).join(", ")}.
        <button type="button" class="btn ghost small-btn" id="show-hidden">Show them</button>`);
      $("#show-hidden").addEventListener("click", () => {
        if (hidden.some((h) => h.name === "view")) state.view = "all";
        for (const h of hidden) document.querySelectorAll(`#filters input[name="${h.name}"]`).forEach((b) => {
          b.checked = h.name in NEGATIVE_FILTERS ? false : true;
        });
        apply();
      });
    } else {
      const where = readFilters().country;
      showNotice(where
        ? "No jobs in this location in the current feed yet. The feed refreshes twice a day; try another country or a longer time window."
        : "No roles match these filters. Try widening them or pressing Reset.");
    }
  } else {
    $("#notice").hidden = true;
  }
}

// Checkbox groups that can hide jobs, and how to describe them when they do.
const GROUP_LABELS = { channel: "Apply via", sponsorship: "Sponsorship evidence", role: "Job role", tier: "Employer tier",
  size: "Employer size", sector: "Sector", domain: "Role domain" };
// Single "only …" checkboxes: ticking them narrows the list.
const NEGATIVE_FILTERS = { english: "English-speaking only", early: "PSW / OPT friendly only", hasContact: "With hiring contact only",
  hideLow: "Rarely sponsored roles hidden" };

// Which single filter, if relaxed, would bring back jobs that match everything else.
function hiddenBy() {
  const f = readFilters();
  const out = [];
  const all = (name) => new Set([...document.querySelectorAll(`#filters input[name="${name}"]`)].map((b) => b.value));
  for (const [name, label] of Object.entries(GROUP_LABELS)) {
    const relaxed = { ...f, [name]: all(name) };
    if (relaxed[name].size === f[name].size) continue;
    const count = state.jobs.filter((j) => matches(j, relaxed)).length;
    if (count) out.push({ name, label: name === "channel" ? "Job boards are switched off under Apply via" : `${label} options unticked`, count });
  }
  for (const [name, label] of Object.entries(NEGATIVE_FILTERS)) {
    if (!f[name]) continue;
    const count = state.jobs.filter((j) => matches(j, { ...f, [name]: false })).length;
    if (count) out.push({ name, label, count });
  }
  if (state.view !== "all") {
    const count = state.jobs.filter((j) => matches(j, f, "all")).length;
    if (count) out.push({ name: "view", label: `the "${VIEWS[state.view].label}" tab`, count });
  }
  return out;
}

function showNotice(html) {
  $("#notice").innerHTML = html;
  $("#notice").hidden = false;
}

function renderMeta(data) {
  const generated = new Date(data.generated_at);
  const staleHours = (Date.now() - generated) / 3_600_000;
  $("#updated").innerHTML = `Updated ${esc(ago(generated))}<br><span class="muted small">${esc(generated.toLocaleString())}</span>`;
  if (staleHours > 36) $("#updated").classList.add("stale");

  const rows = Object.entries(data.sources || {}).map(([name, s]) =>
    `<tr><td>${esc(name)}</td><td><span class="dot ${esc(s.status)}"></span>${esc(s.status)}</td>
     <td>${esc([s.count, s.reason, s.error].filter((v) => v !== undefined && v !== "").join(" · "))}</td></tr>`);
  $("#sources").innerHTML = `<tr><th>Source</th><th>Status</th><th>Records / detail</th></tr>${rows.join("")}`;
  const removed = data.counts?.agency_removed;
  if (removed) {
    $("#sources").insertAdjacentHTML("afterend",
      `<p class="fineprint">${esc(removed)} ${removed === 1 ? "advert" : "adverts"} from recruitment agencies removed in the last run.</p>`);
  }
}

// ------------------------------------------------------------------ CSV
function exportCsv() {
  const cols = ["posted_at", "title", "company", "tier", "size", "sector", "role", "domain", "country", "region",
    "location", "salary", "sponsorship", "sponsor_register", "early_career", "english", "aviation", "channel", "contact_names",
    "contact_emails", "contact_phones", "url", "source"];
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [cols.join(",")];
  for (const j of state.filtered) {
    const list = (k) => j.contacts.map((c) => c[k]).filter(Boolean).join("; ");
    const row = { ...j, contact_names: list("name"), contact_emails: list("email"), contact_phones: list("phone") };
    lines.push(cols.map((c) => cell(row[c])).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob), download: `sponsored-jobs-${new Date().toISOString().slice(0, 10)}.csv`,
  });
  a.click();
  URL.revokeObjectURL(a.href);
}

// ------------------------------------------------------------------ URL state
function syncUrl() {
  const params = new URLSearchParams();
  const form = new FormData($("#filters"));
  for (const [k, v] of form) {
    const el = $(`#filters [name="${k}"]`);
    const isDefault = el?.tagName === "SELECT" && el.selectedIndex === 0;
    if (el?.type !== "checkbox" && v && !isDefault) params.append(k, v);
  }
  // Only record checkbox groups that differ from the default.
  for (const name of ["sponsorship", "channel", "tier", "size", "sector", "domain", "role", "hasContact", "english", "early", "hideLow"]) {
    const boxes = [...document.querySelectorAll(`#filters input[name="${name}"]`)];
    if (boxes.some((b) => b.checked !== b.defaultChecked)) {
      params.set(name, boxes.filter((b) => b.checked).map((b) => b.value).join("|") || "-");
    }
  }
  if ($("#sort").value !== "newest") params.set("sort", $("#sort").value);
  if (state.view !== "all") params.set("view", state.view);
  try {
    history.replaceState(null, "", params.toString() ? `?${params}` : location.pathname);
  } catch { /* embedded or sandboxed viewers may block URL updates; filters still work */ }
}

function restoreUrl() {
  const params = new URLSearchParams(location.search);
  for (const [k, v] of params) {
    if (k === "sort") { $("#sort").value = v; continue; }
    if (k === "view") { if (VIEWS[v]) state.view = v; continue; }
    const boxes = [...document.querySelectorAll(`#filters input[type=checkbox][name="${k}"]`)];
    if (boxes.length) {
      const wanted = new Set(v.split("|"));
      boxes.forEach((b) => { b.checked = wanted.has(b.value); });
    } else {
      const el = $(`#filters [name="${k}"]`);
      if (el) el.value = v;
    }
  }
}

// Feeds written before jobs carried a channel: infer it from the source name.
const OFFICIAL_SOURCES = new Set(["NHS Jobs", "Teaching Vacancies", "jobs.ac.uk", "EURAXESS", "Platsbanken", "Times Higher Education"]);
function legacyChannel(source = "") {
  if (source.endsWith(" careers")) return "career_site";
  return OFFICIAL_SOURCES.has(source) ? "official" : "aggregator";
}

// ------------------------------------------------------------------ boot
async function main() {
  let data;
  try {
    const res = await fetch(DATA_URL, { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    $("#updated").textContent = "Feed unavailable";
    showNotice(`Could not load <code>${DATA_URL}</code> (${esc(err.message)}). If you opened this file directly, serve the folder instead: <code>python -m http.server</code>.`);
    return;
  }
  state.data = data;
  state.jobs = data.jobs.map((j) => ({
    ...j,
    channel: j.channel || legacyChannel(j.source),
    contacts: j.contacts || [],
    sponsor_routes: j.sponsor_routes || [],
    role: j.role || "Other",
    region: j.region || (j.country === "GB" && SCOTLAND_RE.test(`${j.location} ${j.company}`) ? "Scotland" : ""),
    // Feeds from before the language check: only native-English countries can be assumed.
    english: j.english ?? ENGLISH_COUNTRIES.has(j.country),
    early_career: j.early_career || "",
    aviation: j.aviation || "",
    low_sponsorship: !!j.low_sponsorship,
    _posted: new Date(j.posted_at),
    _haystack: [j.title, j.company, j.location, j.region, j.sector, j.domain, j.role, countryName(j.country), j.description,
      j.aviation, ...(j.contacts || []).map((c) => c.name)].join(" ").toLowerCase(),
  }));

  // Country filter: the board's featured countries and regions first, then any other country with jobs.
  const featured = data.featured_countries || DEFAULT_FEATURED;
  const optionLabel = (c) => REGION_OPTIONS[c] ? REGION_OPTIONS[c].label : countryName(c);
  const inWindow = state.jobs.filter((j) => Date.now() - j._posted <= 7 * DAY_MS);
  const option = (c) => `<option value="${esc(c)}">${flag(REGION_OPTIONS[c]?.flag || c)} ${esc(optionLabel(c))} (${
    inWindow.filter((j) => matchesCountry(j, c)).length})</option>`;
  const others = [...new Set(state.jobs.map((j) => j.country))].filter((c) => !featured.includes(c))
    .sort((a, b) => countryName(a).localeCompare(countryName(b)));
  $("select[name=country]").insertAdjacentHTML("beforeend",
    `<optgroup label="Featured">${[...featured.slice(0, 2), "EU", ...featured.slice(2)].map(option).join("")}</optgroup>`
    + (others.length ? `<optgroup label="Other countries">${others.map(option).join("")}</optgroup>` : ""));

  checkboxes("#f-channel", "channel", Object.keys(CHANNELS), (c) => CHANNELS[c], DEFAULT_CHANNELS);
  checkboxes("#f-tier", "tier", ["1", "2", "3"], (t) => `Tier ${t}`);
  checkboxes("#f-size", "size", SIZES, (s) => s[0].toUpperCase() + s.slice(1));
  checkboxes("#f-sector", "sector", data.sectors || []);
  checkboxes("#f-domain", "domain", data.domains || []);
  checkboxes("#f-role", "role", data.roles || ["Other"]);
  $("select[name=aviation]").insertAdjacentHTML("beforeend",
    (data.aviation_families || []).map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join(""));

  fetch(TIERS_URL).then((r) => r.json()).then((cfg) => {
    $("#tier-defs").innerHTML = Object.entries(cfg.tier_definitions || {})
      .map(([t, d]) => `<dt>Tier ${esc(t)}</dt><dd>${esc(d)}</dd>`).join("");
  }).catch(() => {});

  renderMeta(data);
  restoreUrl();
  if (matchMedia("(max-width: 860px)").matches) $("#filter-panel").open = false;

  const form = $("#filters");
  form.addEventListener("input", apply);
  form.addEventListener("reset", () => setTimeout(() => { state.view = "all"; apply(); }));
  $("#sort").addEventListener("change", apply);
  $("#export").addEventListener("click", exportCsv);
  $("#more").addEventListener("click", () => { state.shown += PAGE_SIZE; render(); });
  $("#views").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-view]");
    if (!btn) return;
    state.view = btn.dataset.view;
    apply();
  });
  // "Open roles" in the directory: search the jobs list for that employer.
  $("#employers").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-employer]");
    if (!btn) return;
    $("#filters [name=q]").value = btn.dataset.employer;
    state.view = "all";
    apply();
  });
  document.querySelectorAll("[data-dialog]").forEach((b) =>
    b.addEventListener("click", () => document.getElementById(b.dataset.dialog).showModal()));

  apply();
}

main();
