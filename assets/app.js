const DATA_URL = "data/jobs.json";
const TIERS_URL = "config/company_tiers.json";
const PAGE_SIZE = 40;
const DAY_MS = 86_400_000;

const SIZES = ["large", "medium", "small", "unknown"];
const COUNTRY_NAMES = new Intl.DisplayNames(["en"], { type: "region" });
const $ = (sel) => document.querySelector(sel);

const state = { data: null, jobs: [], filtered: [], shown: PAGE_SIZE };

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

function checkboxes(container, name, values, labelFn = (v) => v) {
  const el = $(container);
  for (const v of values) {
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" name="${name}" value="${esc(v)}" checked> ${esc(labelFn(v))} <span class="count" data-count="${name}:${esc(v)}"></span>`;
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
    tier: new Set(form.getAll("tier")),
    size: new Set(form.getAll("size")),
    sector: new Set(form.getAll("sector")),
    domain: new Set(form.getAll("domain")),
  };
}

function matches(job, f) {
  if (Date.now() - job._posted > f.days * DAY_MS) return false;
  if (f.country === "GB" && job.country !== "GB") return false;
  if (f.country === "EU" && job.country === "GB") return false;
  if (f.country.length === 2 && f.country !== "GB" && job.country !== f.country) return false;
  if (!f.sponsorship.has(job.sponsorship)) return false;
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
    ["With contact email", jobs.filter((j) => j.contacts.length).length],
    ["UK / Europe", `${jobs.filter((j) => j.country === "GB").length} / ${jobs.filter((j) => j.country !== "GB").length}`],
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
  const label = [c.name, c.role].filter(Boolean).join(", ");
  const badge = c.provenance === "verified"
    ? `<a class="tag ok" href="${esc(safeUrl(c.source_url))}" target="_blank" rel="noopener" title="Verified ${esc(c.verified_on)}">verified</a>`
    : `<span class="tag" title="Published in the job advert">from advert</span>`;
  return `<li><a href="mailto:${esc(c.email)}">${esc(c.email)}</a>
    <span class="muted">${esc(label || c.type)}</span> ${badge}</li>`;
}

function jobHtml(j) {
  const sponsorTag = j.sponsorship === "confirmed"
    ? `<span class="tag ok" title="The advert states visa sponsorship is available">Sponsorship offered</span>`
    : `<span class="tag warn" title="Employer is on the official sponsor register but the advert does not mention sponsorship — ask before applying">Licensed sponsor</span>`;
  const register = j.sponsor_register
    ? `<span class="tag" title="${esc(j.sponsor_routes.join(", "))}">${esc(j.sponsor_register)} register</span>` : "";
  const linkedin = `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(`${j.company} talent acquisition OR recruiter OR hiring manager`)}`;
  const contacts = j.contacts.length
    ? `<ul class="contacts">${j.contacts.map(contactHtml).join("")}</ul>`
    : `<p class="muted small">No hiring email published — apply via the advert, or <a href="${esc(linkedin)}" target="_blank" rel="noopener">find the recruiter on LinkedIn</a>.</p>`;

  return `<li class="job">
    <div class="job-head">
      <h2><a href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener">${esc(j.title)}</a></h2>
      <span class="posted" title="${esc(j._posted.toLocaleString())}">${ago(j._posted)}</span>
    </div>
    <p class="employer"><strong>${esc(j.company || "Employer not stated")}</strong>
      <span class="tier t${j.tier}">Tier ${j.tier}</span>
      <span class="muted">${esc(j.size === "unknown" ? "size unknown" : j.size)}</span></p>
    <p class="meta">${flag(j.country)} ${esc(j.location || countryName(j.country))}
      ${j.salary ? ` · ${esc(j.salary)}` : ""}${j.contract ? ` · ${esc(j.contract)}` : ""}</p>
    <p class="tags">${sponsorTag}${register}<span class="tag">${esc(j.sector)}</span><span class="tag">${esc(j.domain)}</span></p>
    ${j.description ? `<p class="desc">${esc(j.description)}</p>` : ""}
    <div class="job-foot">
      <div class="contact-block"><h3>Hiring contact</h3>${contacts}</div>
      <a class="btn" href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener">View &amp; apply</a>
    </div>
    <p class="source muted small">via ${esc(j.source)}</p>
  </li>`;
}

function render() {
  renderStats();
  const { filtered, shown } = state;
  $("#summary").textContent = `${filtered.length} of ${state.jobs.length} roles match`;
  $("#jobs").innerHTML = filtered.slice(0, shown).map(jobHtml).join("");
  $("#more").hidden = filtered.length <= shown;

  if (!state.jobs.length) {
    showNotice(`No jobs in the feed yet. Run the <strong>Refresh sponsored jobs</strong> workflow in the repository's
      Actions tab (and add the optional API keys described in the README) to populate it.`);
  } else if (!filtered.length) {
    showNotice("No roles match these filters. Try widening them or pressing Reset.");
  } else {
    $("#notice").hidden = true;
  }
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
     <td>${esc(s.count ?? s.reason ?? s.error ?? "")}</td></tr>`);
  $("#sources").innerHTML = `<tr><th>Source</th><th>Status</th><th>Records / detail</th></tr>${rows.join("")}`;
}

// ------------------------------------------------------------------ CSV
function exportCsv() {
  const cols = ["posted_at", "title", "company", "tier", "size", "sector", "domain", "country", "location",
    "salary", "sponsorship", "sponsor_register", "contact_emails", "url", "source"];
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [cols.join(",")];
  for (const j of state.filtered) {
    const row = { ...j, contact_emails: j.contacts.map((c) => c.email).join("; ") };
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
  for (const name of ["sponsorship", "tier", "size", "sector", "domain", "hasContact"]) {
    const boxes = [...document.querySelectorAll(`#filters input[name="${name}"]`)];
    if (boxes.some((b) => b.checked !== b.defaultChecked)) {
      params.set(name, boxes.filter((b) => b.checked).map((b) => b.value).join("|") || "-");
    }
  }
  if ($("#sort").value !== "newest") params.set("sort", $("#sort").value);
  history.replaceState(null, "", params.toString() ? `?${params}` : location.pathname);
}

function restoreUrl() {
  const params = new URLSearchParams(location.search);
  for (const [k, v] of params) {
    if (k === "sort") { $("#sort").value = v; continue; }
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
    _posted: new Date(j.posted_at),
    _haystack: [j.title, j.company, j.location, j.sector, j.domain, countryName(j.country), j.description]
      .join(" ").toLowerCase(),
  }));

  const countries = [...new Set(state.jobs.map((j) => j.country))].filter((c) => c !== "GB").sort();
  $("select[name=country]").insertAdjacentHTML("beforeend",
    countries.map((c) => `<option value="${esc(c)}">${flag(c)} ${esc(countryName(c))}</option>`).join(""));

  checkboxes("#f-tier", "tier", ["1", "2", "3"], (t) => `Tier ${t}`);
  checkboxes("#f-size", "size", SIZES, (s) => s[0].toUpperCase() + s.slice(1));
  checkboxes("#f-sector", "sector", data.sectors || []);
  checkboxes("#f-domain", "domain", data.domains || []);

  fetch(TIERS_URL).then((r) => r.json()).then((cfg) => {
    $("#tier-defs").innerHTML = Object.entries(cfg.tier_definitions || {})
      .map(([t, d]) => `<dt>Tier ${esc(t)}</dt><dd>${esc(d)}</dd>`).join("");
  }).catch(() => {});

  renderMeta(data);
  restoreUrl();
  if (matchMedia("(max-width: 860px)").matches) $("#filter-panel").open = false;

  const form = $("#filters");
  form.addEventListener("input", apply);
  form.addEventListener("reset", () => setTimeout(apply));
  $("#sort").addEventListener("change", apply);
  $("#export").addEventListener("click", exportCsv);
  $("#more").addEventListener("click", () => { state.shown += PAGE_SIZE; render(); });
  document.querySelectorAll("[data-dialog]").forEach((b) =>
    b.addEventListener("click", () => document.getElementById(b.dataset.dialog).showModal()));

  apply();
}

main();
