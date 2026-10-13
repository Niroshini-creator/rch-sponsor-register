"use strict";
const $app = document.getElementById("app");
const state = { me: null, options: null, view: "jobs", jobs: null, q: "", showBelow: false, offset: 0, track: "", country: "", sponsoredOnly: false };

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}
const STATIC = typeof window !== "undefined" && !!window.LocalApi;  // the browser-only test version
async function api(method, path, body) {
  if (STATIC) return LocalApi.call(method, path, body);
  const res = await fetch(path, { method, headers: { "X-Requested-With": "matcher", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
  const ctype = res.headers.get("content-type") || "";
  const data = ctype.includes("json") ? await res.json() : await res.blob();
  if (!res.ok) { const e = new Error(data.error || "Something went wrong"); e.status = res.status; throw e; }
  return data;
}
const money = (cur, n) => cur + Number(n).toLocaleString("en-GB");
const days = iso => { const d = Math.floor((Date.now() - new Date(iso)) / 864e5); return d <= 0 ? "today" : d === 1 ? "1 day ago" : d + " days ago"; };
function toBase64(bytes) {
  let bin = ""; for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
const lines = s => s.split(/[\n,]/).map(x => x.trim()).filter(Boolean);

async function boot() {
  try {
    state.options = await api("GET", "/api/options");
    try { state.me = await api("GET", "/api/me"); } catch { state.me = null; }
  } catch (x) { $app.replaceChildren(h("div", { class: "card" }, h("h1", {}, "Couldn't load"), h("p", { class: "err" }, x.message), h("p", { class: "muted" }, "Open this page from a web address (not by double-clicking the file) and check your connection."))); return; }
  if (STATIC) { document.getElementById("logout").hidden = true; document.title = "Candidate Job Matcher (test)"; showNotice(); }
  render();
}
function render() {
  const nav = document.getElementById("nav");
  nav.hidden = !state.me;
  if (!state.me) return authView();
  if (!state.me.has_profile && state.view !== "profile" && !(STATIC && state.view === "account")) state.view = "profile";
  nav.querySelectorAll("button[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === state.view));
  ({ jobs: jobsView, applications: applicationsView, profile: profileView, tracks: tracksView, employers: employersView, thresholds: thresholdsView, account: accountView })[state.view]();
}
document.getElementById("nav").addEventListener("click", e => { if (e.target.dataset.view) { state.view = e.target.dataset.view; render(); } });
document.getElementById("logout").addEventListener("click", async () => { await api("POST", "/api/logout", {}); state.me = null; render(); });

function showNotice() {
  const box = document.getElementById("notice"); if (!box) return;
  const blocked = state.me && state.me.storage_ok === false;
  box.hidden = false;
  box.replaceChildren(h("strong", {}, "Test version. "), "Your profile, CVs and tracked jobs are saved only in this browser on this device; nothing is uploaded. ",
    h("a", { href: "#", onclick: e => { e.preventDefault(); state.view = "account"; render(); } }, "Export or reset your data"),
    blocked ? h("div", { class: "err" }, "This browser is blocking storage, so your details will be lost when you close the tab. Export them from Account before leaving.") : "");
}

function authView() {
  let mode = "login"; const err = h("div", { class: "err", role: "alert" });
  const email = h("input", { type: "email", autocomplete: "email", required: true });
  const pw = h("input", { type: "password", autocomplete: "current-password", required: true });
  const invite = h("input", { type: "text" });
  const consent = h("input", { type: "checkbox" });
  const inviteRow = h("div", { hidden: true }, h("label", {}, "Invite code"), invite);
  const consentRow = h("label", { class: "check", hidden: true }, consent, h("span", {}, "I agree that my CVs, visa details and job preferences are stored here to match me with vacancies. I can export or delete them at any time under Account. ", h("a", { href: "/privacy", target: "_blank" }, "Read the privacy notice")));
  const submit = h("button", { class: "btn primary", type: "submit" }, "Sign in");
  const toggle = h("button", { class: "btn", type: "button" }, "Create an account instead");
  function setMode(m) {
    mode = m; const reg = m === "register";
    submit.textContent = reg ? "Create account" : "Sign in";
    toggle.textContent = reg ? "I already have an account" : "Create an account instead";
    consentRow.hidden = !reg; inviteRow.hidden = !(reg && state.options.invite_required);
    pw.autocomplete = reg ? "new-password" : "current-password";
  }
  toggle.onclick = () => setMode(mode === "login" ? "register" : "login");
  const form = h("form", { class: "card", onsubmit: async e => {
    e.preventDefault(); err.textContent = "";
    try {
      await api("POST", mode === "login" ? "/api/login" : "/api/register",
        { email: email.value, password: pw.value, invite: invite.value, consent: consent.checked });
      state.me = await api("GET", "/api/me"); state.view = state.me.has_profile ? "jobs" : "profile"; render();
    } catch (x) { err.textContent = x.message; }
  } }, h("h1", {}, "Find jobs that fit your visa"),
    h("p", { class: "muted" }, "Sign in to see vacancies matched to your resume, preferred roles and visa situation, with the visa salary check and hiring contacts shown on each post."),
    h("label", {}, "Email"), email, h("label", {}, "Password (10+ characters)"), pw, inviteRow, consentRow, err,
    h("div", { class: "actions" }, submit, toggle));
  $app.replaceChildren(form);
}

const MODE_TEXT = {
  required: "I need an employer to sponsor me now",
  preferred: "I can work now, but want an employer who can sponsor me later (placement first, sponsors preferred)",
  not_needed: "I don't need sponsorship" };
const ordinal = n => ({ 1: "1st choice", 2: "2nd choice", 3: "3rd choice" }[n] || n + "th choice");
function field(label, el, hint) { return h("div", {}, h("label", {}, label), el, hint ? h("div", { class: "muted small" }, hint) : ""); }

async function samplePicker() {
  const list = await LocalApi.personas();
  return h("div", { class: "card" }, h("h2", {}, "Just testing? Try a sample candidate"),
    h("p", { class: "muted small" }, "Loads a fictional profile with CVs so you can see the matches straight away. You can change everything afterwards."),
    ...list.map(x => h("div", { class: "actions", style: "align-items:flex-start;flex-wrap:nowrap" },
      h("button", { class: "btn", onclick: async () => { await LocalApi.loadPersona(x.key); state.me = await api("GET", "/api/me"); state.jobs = null; state.view = "jobs"; render(); } }, "Load"),
      h("span", {}, h("strong", {}, x.label), h("div", { class: "muted small" }, x.about)))));
}

function profileView() {
  const p = state.me.profile, o = state.options; const err = h("div", { class: "err", role: "alert" });
  const f = {}; const ms = p.min_salary || {};
  const flag = (key, label) => { f[key] = h("input", { type: "checkbox" }); f[key].checked = !!p[key]; return h("label", { class: "check" }, f[key], h("span", {}, label)); };
  const num = (v, step) => h("input", { type: "number", min: 0, step: step || 1, value: v || "" });
  f.full_name = h("input", { type: "text", value: p.full_name || "" }); f.phone = h("input", { type: "tel", value: p.phone || "" });
  f.visa_expiry = h("input", { type: "date", value: p.visa_expiry || "" });
  f.visa_type = h("select", { onchange: () => { f.sponsorship_mode.value = o.visa_modes[f.visa_type.value]; } },
    Object.entries(o.visa_types).map(([k, v]) => h("option", { value: k, selected: p.visa_type === k }, v)));
  f.sponsorship_mode = h("select", {}, Object.entries(MODE_TEXT).map(([k, v]) => h("option", { value: k, selected: p.sponsorship_mode === k }, v)));
  f.locations = h("textarea", { rows: 2, placeholder: "e.g. London, Manchester, Dublin, Remote" }); f.locations.value = (p.locations || []).join(", ");
  f.sGB = num(ms.GB); f.sIE = num(ms.IE); f.sEU = num(ms.EU); f.sIN = num(ms.IN, 0.5);
  const countryBoxes = Object.entries(o.countries).map(([k, v]) => { const c = h("input", { type: "checkbox", value: k }); c.checked = (p.countries || []).includes(k); return [c, h("label", { class: "check" }, c, v)]; });
  const sectorBoxes = o.sectors.map(x => { const c = h("input", { type: "checkbox", value: x }); c.checked = (p.sectors || []).includes(x); return [c, h("label", { class: "check" }, c, x)]; });
  const save = h("button", { class: "btn primary", type: "button", onclick: async () => {
    err.textContent = "";
    const body = { visa_type: f.visa_type.value, visa_expiry: f.visa_expiry.value, full_name: f.full_name.value, phone: f.phone.value,
      sponsorship_mode: f.sponsorship_mode.value, new_entrant: f.new_entrant.checked, phd: f.phd.checked, shortage_role: f.shortage_role.checked,
      graduate_only: f.graduate_only.checked, sponsored_only: f.sponsored_only.checked, open_to_europe: f.open_to_europe.checked, open_to_india: f.open_to_india.checked,
      locations: lines(f.locations.value), target_roles: p.target_roles || [], keywords: p.keywords || [], consent_privacy: true,
      min_salary: { GB: Number(f.sGB.value || 0), IE: Number(f.sIE.value || 0), EU: Number(f.sEU.value || 0), IN: Number(f.sIN.value || 0) },
      countries: countryBoxes.filter(([c]) => c.checked).map(([c]) => c.value), sectors: sectorBoxes.filter(([c]) => c.checked).map(([c]) => c.value) };
    try { const first = !state.me.has_profile; await api("PUT", "/api/profile", body); state.me = await api("GET", "/api/me"); state.jobs = null;
      state.view = first || !state.me.tracks.length ? "tracks" : "jobs"; render(); }
    catch (x) { err.textContent = x.message; }
  } }, "Save profile");
  const sampleBox = h("div"); if (STATIC && !state.me.has_profile) samplePicker().then(el => sampleBox.replaceChildren(el));
  $app.replaceChildren(h("h1", {}, "Your profile"), sampleBox,
    h("div", { class: "card" }, h("h2", {}, "About you"), h("div", { class: "row" }, field("Full name", f.full_name), field("Phone (optional)", f.phone))),
    h("div", { class: "card" }, h("h2", {}, "Visa and sponsorship"),
      h("div", { class: "row" }, field("Visa / status", f.visa_type), field("Visa expiry date", f.visa_expiry, "Sponsoring employers are ranked higher as this gets close.")),
      field("Sponsorship", f.sponsorship_mode),
      flag("sponsored_only", "Show sponsoring employers only (hides adverts that say they can't sponsor)"),
      flag("new_entrant", "New entrant: under 26, a recent graduate, or switching from a Graduate/Student visa (lower UK salary minimum)"),
      flag("phd", "The role needs a PhD relevant to the job (lower UK salary minimum)"),
      flag("shortage_role", "My occupation is on the Immigration Salary List (lower UK salary minimum)"),
      flag("graduate_only", "Show graduate and early-career roles only")),
    h("div", { class: "card" }, h("h2", {}, "Where you'll work"), h("label", {}, "Countries"), h("div", { class: "row" }, countryBoxes.map(x => x[1])),
      flag("open_to_europe", "Also show roles anywhere in Europe, but only where the employer offers or holds a licence to sponsor"),
      flag("open_to_india", "I'd move to India for a good package (set the minimum below)"),
      field("Preferred places", f.locations, "Cities or regions in your chosen countries. Leave empty for anywhere."),
      h("label", {}, "Minimum pay you'll accept (yearly, optional)"),
      h("div", { class: "row" }, field("UK (£)", f.sGB), field("Ireland (€)", f.sIE), field("Elsewhere in Europe (€)", f.sEU), field("India (lakhs per annum, LPA)", f.sIN, "e.g. 25 means ₹25,00,000"))),
    h("div", { class: "card" }, h("h2", {}, "Sectors"), h("p", { class: "muted small" }, "Leave all unticked for any sector."), h("div", { class: "row" }, sectorBoxes.map(x => x[1]))),
    err, h("div", { class: "actions" }, save));
}

function trackCard(t, reload) {
  const err = h("div", { class: "err", role: "alert" }); const status = h("span", { class: "muted small" });
  const name = h("input", { type: "text", value: t.name });
  const prio = h("select", {}, [1, 2, 3, 4, 5].map(n => h("option", { value: n, selected: t.priority === n }, ordinal(n))));
  const roles = h("textarea", { rows: 3 }); roles.value = t.target_roles.join("\n");
  const kws = h("textarea", { rows: 3 }); kws.value = t.keywords.join(", ");
  const file = h("input", { type: "file", accept: ".docx,.pdf,.txt,.md" });
  const pasted = h("textarea", { rows: 4, placeholder: "Or paste this CV's text (only needed if a file can't be read, e.g. a scanned PDF)" });
  const cvInfo = h("div", { class: "small" }, t.filename ? ["CV for this domain: ", h("strong", {}, t.filename), STATIC ? " (text saved in this browser; keep your original file to apply)" : "", " "] : h("span", { class: "muted" }, "No CV uploaded for this domain yet. "),
    t.filename && !STATIC ? h("a", { href: "#", onclick: async e => { e.preventDefault(); const b = await api("GET", `/api/tracks/${t.id}/resume`); h("a", { href: URL.createObjectURL(b), download: t.filename }).click(); } }, "Download") : "");
  const upload = h("button", { class: "btn", type: "button", onclick: async () => {
    err.textContent = ""; const fl = file.files[0];
    if (!fl && !pasted.value.trim()) { err.textContent = "Choose a file or paste the CV text."; return; }
    try {
      const data = fl ? toBase64(new Uint8Array(await fl.arrayBuffer())) : btoa(unescape(encodeURIComponent(pasted.value)));
      const r = await api("POST", `/api/tracks/${t.id}/resume`, { filename: fl ? fl.name : "cv.txt", data, text: pasted.value });
      state.cvMessage = r.needs_text
        ? { cls: "warn", text: `"${r.filename}" was saved, but no text could be read from it (a scanned PDF is only a picture). Paste the CV text into the box under the file chooser for "${t.name}", then press Upload CV again.` }
        : { cls: "ok", text: `Read "${r.filename}" for "${t.name}": ${r.keywords.length} skills and keywords found. Check them below, edit if needed, then press Save.` };
      await reload();
    } catch (x) { err.textContent = x.message; }
  } }, t.filename ? "Replace CV" : "Upload CV");
  const save = h("button", { class: "btn primary", type: "button", onclick: async () => {
    err.textContent = "";
    try { await api("PUT", `/api/tracks/${t.id}`, { name: name.value, priority: Number(prio.value), target_roles: lines(roles.value), keywords: lines(kws.value) });
      state.jobs = null; status.textContent = "Saved."; await reload(); } catch (x) { err.textContent = x.message; }
  } }, "Save");
  const del = h("button", { class: "btn danger", type: "button", onclick: async () => { if (confirm(`Remove "${t.name}" and its CV?`)) { await api("DELETE", `/api/tracks/${t.id}`); state.jobs = null; await reload(); } } }, "Remove");
  return h("div", { class: "card" }, h("div", { class: "row" }, field("Domain", name), field("Priority", prio)),
    field("Roles to look for", roles, "One per line, e.g. Business Analyst, Systems Analyst"), field("Skills & keywords from this CV", kws),
    cvInfo, file, pasted, err, h("div", { class: "actions" }, upload, save, del, status));
}

async function tracksView() {
  const box = h("div"); const sugg = h("div");
  const nameIn = h("input", { type: "text", placeholder: "e.g. Data Analyst" });
  const reload = async () => { state.me = await api("GET", "/api/me"); draw(); };
  function draw() {
    const tracks = state.me.tracks;
    const msg = state.cvMessage; state.cvMessage = null;
    box.replaceChildren(msg ? h("div", { class: "box " + msg.cls, role: "status" }, msg.text) : "", ...tracks.map(t => h("div", {}, h("h2", {}, `${ordinal(t.priority)}: ${t.name}`), trackCard(t, reload))),
      tracks.length ? "" : h("p", { class: "muted" }, "Add a domain for each kind of role you want, e.g. Business Analyst and Data Analyst, and attach the CV tailored to it."));
  }
  const add = async (name, roles, priority) => { try { await api("POST", "/api/tracks", { name, target_roles: roles || [name], priority }); state.jobs = null; await reload(); } catch (x) { alert(x.message); } };
  const suggest = h("button", { class: "btn primary", onclick: async () => {
    sugg.replaceChildren(h("p", { class: "muted" }, "Reading your CV and counting open vacancies…"));
    try {
      const r = await api("POST", "/api/suggestions", {});
      sugg.replaceChildren(h("p", { class: "muted small" }, `Ranked by how well your CV fits and how many vacancies are open to you under your visa rules (from ${r.feed_jobs.toLocaleString("en-GB")} jobs).`),
        ...r.suggestions.map(x => h("div", { class: "card" },
          h("strong", {}, x.role), x.suggested_priority ? h("span", { class: "tag ok", style: "margin-left:8px" }, "Suggested " + ordinal(x.suggested_priority)) : "",
          h("div", { class: "small" }, `CV fit ${x.fit}% · ${x.vacancies} open vacancies for you now`),
          x.skills.length ? h("div", { class: "small muted" }, "Evidence: " + x.skills.join(", ") + (x.past_titles.length ? " · past titles: " + x.past_titles.join(", ") : "")) : "",
          x.already_added ? h("span", { class: "tag" }, "Already added") : h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => add(x.role, [x.role], x.suggested_priority || state.me.tracks.length + 1) }, `Add as ${ordinal(x.suggested_priority || state.me.tracks.length + 1)}`)))));
    } catch (x) { sugg.replaceChildren(h("p", { class: "err" }, x.message)); }
  } }, "Suggest roles from my CV");
  $app.replaceChildren(h("h1", {}, "My CVs & roles"),
    h("p", { class: "muted" }, "Keep one CV per domain and rank them. Jobs are matched against every domain; the best fit is shown with the CV to use, and your first choice ranks highest."),
    box, h("div", { class: "card" }, h("h2", {}, "Add a domain"), h("div", { class: "row" }, nameIn, h("button", { class: "btn primary", onclick: () => { if (nameIn.value.trim()) add(nameIn.value.trim(), null, state.me.tracks.length + 1); } }, "Add domain"))),
    h("div", { class: "card" }, h("h2", {}, "Not sure which roles suit you?"), h("p", { class: "muted small" }, "Upload a CV above, then get ranked suggestions for your first, second and third choice."), suggest), sugg);
  draw();
}

async function loadJobs() {
  const qs = new URLSearchParams({ q: state.q, offset: state.offset, limit: 25, show_below: state.showBelow ? "1" : "0",
    track: state.track || "", country: state.country || "", sponsored_only: state.sponsoredOnly ? "1" : "0" });
  state.jobs = await api("GET", "/api/jobs?" + qs);
}
async function jobsView() {
  const prof = state.me.profile, o = state.options;
  const search = h("input", { type: "text", placeholder: "Search title, employer or place", value: state.q });
  const below = h("input", { type: "checkbox" }); below.checked = state.showBelow;
  const spon = h("input", { type: "checkbox" }); spon.checked = !!state.sponsoredOnly;
  const trackSel = h("select", {}, h("option", { value: "" }, "All my CVs / domains"),
    state.me.tracks.map(t => h("option", { value: t.id, selected: String(state.track) === String(t.id) }, `${ordinal(t.priority)}: ${t.name}`)));
  const countrySel = h("select", {});
  const list = h("div", {}, h("p", { class: "muted" }, "Finding matches…"));
  const reload = async () => { state.q = search.value; state.showBelow = below.checked; state.sponsoredOnly = spon.checked; state.track = trackSel.value; state.country = countrySel.value; state.offset = 0; await loadJobs(); draw(); };
  const left = prof.visa_expiry ? Math.round((new Date(prof.visa_expiry) - Date.now()) / 864e5) : null;
  const banner = (prof.sponsorship_mode === "preferred" && left !== null && left <= 365)
    ? h("div", { class: "box " + (left <= 90 ? "bad" : "warn") }, left < 0 ? "Your visa has expired. " : `Your visa expires in ${left} days. `, "Employers who can sponsor are ranked first. Check the visa minimum on each card.") : "";
  const feedAge = state.me.feed && state.me.feed.generated_at ? (Date.now() - new Date(state.me.feed.generated_at)) / 36e5 : null;
  const stale = feedAge !== null && feedAge > 72 ? h("div", { class: "box warn" }, `The vacancy feed was last refreshed ${Math.round(feedAge / 24)} days ago, so some jobs may have closed. Check each advert before applying.`) : "";
  function draw() {
    const d = state.jobs; const feed = state.me.feed || {};
    countrySel.replaceChildren(h("option", { value: "" }, "All countries"), ...Object.entries(d.by_country).sort((a, b) => b[1] - a[1]).map(([c, n]) => h("option", { value: c, selected: state.country === c }, `${o.countries[c] || c} (${n})`)));
    list.replaceChildren(h("p", { class: "muted small" }, `${d.total} matching jobs${feed.generated_at ? " · feed updated " + new Date(feed.generated_at).toLocaleString("en-GB") : ""}`),
      ...d.jobs.map(jobCard),
      h("div", { class: "actions" },
        d.offset > 0 && h("button", { class: "btn", onclick: async () => { state.offset = Math.max(0, d.offset - 25); await loadJobs(); draw(); window.scrollTo(0, 0); } }, "Previous"),
        d.offset + 25 < d.total && h("button", { class: "btn", onclick: async () => { state.offset = d.offset + 25; await loadJobs(); draw(); window.scrollTo(0, 0); } }, "Next")));
  }
  $app.replaceChildren(h("h1", {}, "Matched jobs"), banner, stale,
    !state.me.tracks.length ? h("div", { class: "box warn" }, "Add your CVs and the roles you want under ", h("a", { href: "#", onclick: e => { e.preventDefault(); state.view = "tracks"; render(); } }, "My CVs & roles"), " for better matches.") : "",
    h("div", { class: "card" }, h("div", { class: "row" }, search, h("button", { class: "btn primary", onclick: reload }, "Search")),
      h("div", { class: "row" }, field("CV / domain", trackSel), field("Country", countrySel)),
      prof.sponsorship_mode === "preferred" ? h("label", { class: "check" }, spon, h("span", {}, "Sponsoring employers only")) : "",
      h("label", { class: "check" }, below, h("span", {}, "Also show jobs whose pay is below my minimum"))), list);
  try { if (!state.jobs) await loadJobs(); draw(); } catch (x) { list.replaceChildren(h("p", { class: "err" }, x.message)); }
}
function jobCard(j) {
  const pc = j.pay_check; const cls = { meets: "ok", partial: "warn", below: "bad", unstated: "warn", not_needed: "ok", unchecked: "" }[pc.status];
  const pkg = pc.kind === "package";
  const title = pkg
    ? { meets: "Package meets your minimum", below: "Package is below your minimum", unstated: "Package not stated: ask before applying", unchecked: "Set a minimum package to compare" }[pc.status]
    : { meets: "Meets the visa salary minimum", partial: "Partly meets the visa salary minimum", below: "Below the visa salary minimum",
      unstated: "Pay not stated: check before applying", not_needed: "Visa minimum not applicable", unchecked: "No visa salary check for this country" }[pc.status];
  const pay = pkg ? (pc.lakhs ? pc.lakhs + " (" + money("₹", pc.pay_low) + (pc.pay_low !== pc.pay_high ? " – " + money("₹", pc.pay_high) : "") + ")" : (j.salary || "Not stated"))
    : pc.pay_high ? (pc.pay_low === pc.pay_high ? money(pc.currency, pc.pay_high) : money(pc.currency, pc.pay_low) + " – " + money(pc.currency, pc.pay_high)) + " a year" : (j.salary || "Not stated");
  const contact = j.contacts.length
    ? j.contacts.map(c => h("div", {}, h("strong", {}, c.name || (c.type || "Contact")), c.role ? ", " + c.role : "", " · ", h("a", { href: "mailto:" + c.email }, c.email), c.phone ? " · " + c.phone : "",
        h("span", { class: "muted small" }, c.provenance === "verified" ? " (verified)" : " (from the advert)")))
    : [h("span", { class: "muted" }, "No hiring contact is published in this advert. "),
       j.recruiter_search ? h("a", { href: j.recruiter_search, target: "_blank", rel: "noopener noreferrer" }, "Find the recruiter on LinkedIn") : ""];
  const statusSel = h("select", { onchange: async e => { await api("POST", "/api/applications", { job_id: j.id, status: e.target.value, track: j.track.name, cv: j.track.cv }); j.application_status = e.target.value; } },
    h("option", { value: "" }, "Track this job…"), state.options.statuses.map(x => h("option", { value: x, selected: j.application_status === x }, x[0].toUpperCase() + x.slice(1))));
  statusSel.querySelector("option[value='']").disabled = !!j.application_status;
  const sponsorCls = ["not_sponsored"].includes(j.sponsorship) ? "bad" : (j.sponsorship === "domestic" ? "" : "ok");
  return h("article", { class: "card job" },
    h("span", { class: "score", title: "Match score" }, j.match + "%"),
    h("h3", {}, j.title), h("div", { class: "meta" }, `${j.company} · ${j.location} · ${state.options.countries[j.country] || j.country} · posted ${days(j.posted_at)} · ${j.sector}`),
    h("div", {}, h("span", { class: "tag " + sponsorCls }, j.sponsorship_label), j.early_career ? h("span", { class: "tag" }, "Graduate friendly") : ""),
    h("div", { class: "box" }, h("strong", {}, `${ordinal(j.track.priority)}: ${j.track.name}`),
      h("div", { class: "small" }, j.track.cv ? "Apply with your CV: " + j.track.cv : "Use your CV for this domain")),
    h("div", { class: "box " + cls }, h("strong", {}, title), h("div", {}, `Advertised pay: ${pay}`),
      pc.floor ? h("div", {}, `${pkg ? "Your minimum" : "Applies to you"}: ${pkg ? pc.floor / 100000 + " LPA" : money(pc.currency, pc.floor) + " (" + pc.floor_label + ") · " + pc.route}`) : "", h("div", { class: "small" }, pc.note),
      pc.thresholds.length ? h("details", {}, h("summary", {}, "All thresholds"), h("ul", { class: "plain" },
        pc.thresholds.map(t => h("li", {}, `${t.label}: ${money(pc.currency, t.amount)}`, pc.pay_high ? (t.met ? " ✓ reached" : " ✗ not reached") : "")))) : ""),
    h("div", { class: "box" }, h("strong", {}, "Hiring contact"), h("div", {}, contact)),
    h("details", {}, h("summary", {}, "Why this score"), h("ul", { class: "plain" }, j.match_parts.map(x => h("li", {}, `${x.label}: ${x.points}${x.max ? "/" + x.max : ""}${x.detail ? " – " + x.detail : ""}`)))),
    j.description ? h("p", { class: "small muted" }, j.description) : "",
    h("div", { class: "actions" }, j.url ? h("a", { class: "btn primary", href: j.url, target: "_blank", rel: "noopener noreferrer",
      onclick: () => { if (!j.application_status) api("POST", "/api/applications", { job_id: j.id, status: "saved", track: j.track.name, cv: j.track.cv }).then(() => { j.application_status = "saved"; }); } }, "Apply on employer site") : "",
      j.employer_site ? h("a", { class: "btn", href: j.employer_site, target: "_blank", rel: "noopener noreferrer" }, "Employer careers site") : "", statusSel));
}

const CATEGORY_NOTE = { "Job board": "Job board: search it yourself", "Official": "Official portal" };
async function employersView() {
  const st = state.emp || (state.emp = { q: "", country: "", category: "" });
  const o = state.options;
  const search = h("input", { type: "text", placeholder: "Search employers and portals", value: st.q });
  const countrySel = h("select", {}); const catSel = h("select", {});
  const list = h("div", {}, h("p", { class: "muted" }, "Loading career sites…"));
  const load = async () => {
    st.q = search.value; st.country = countrySel.value; st.category = catSel.value;
    const qs = new URLSearchParams({ q: st.q, country: st.country, category: st.category });
    const d = await api("GET", "/api/employers?" + qs);
    countrySel.replaceChildren(h("option", { value: "" }, "All countries"), ...Object.entries(d.countries).sort((a, b) => b[1] - a[1]).map(([c, n]) => h("option", { value: c, selected: st.country === c }, `${c === "EU" ? "Europe-wide" : o.countries[c] || c} (${n})`)));
    catSel.replaceChildren(h("option", { value: "" }, "All types"), ...Object.entries(d.categories).map(([c, n]) => h("option", { value: c, selected: st.category === c }, `${c} (${n})`)));
    list.replaceChildren(h("p", { class: "muted small" }, `${d.sites.length} career sites and portals. Links open the organisation's own site; vacancy counts come from this platform's feed.`),
      ...d.sites.map(r => h("div", { class: "card" },
        h("strong", {}, r.name), " ", h("span", { class: "tag" }, r.country === "EU" ? "Europe" : o.countries[r.country] || r.country), h("span", { class: "tag" }, r.category),
        r.licensed_sponsor ? h("span", { class: "tag ok" }, "Licensed sponsor") : "", r.link_type === "board" ? h("span", { class: "tag warn", title: "Link to the employer's applicant-tracking board; it may have moved" }, "Job board link") : "",
        r.note ? h("div", { class: "small muted" }, r.note) : "",
        h("div", { class: "actions" }, h("a", { class: "btn primary", href: r.careers_url, target: "_blank", rel: "noopener noreferrer" }, CATEGORY_NOTE[r.category] === undefined ? "Open careers site" : "Open site"),
          r.open_total ? h("button", { class: "btn", onclick: () => { state.q = r.name.replace(/\s*\(.*\)$/, ""); state.country = r.country; state.jobs = null; state.offset = 0; state.view = "jobs"; render(); } },
            `${r.open_for_you} open for you${r.open_total !== r.open_for_you ? " (" + r.open_total + " in feed)" : ""}`) : (CATEGORY_NOTE[r.category] ? "" : h("span", { class: "muted small" }, "No vacancies from this employer in the feed right now"))))));
  };
  $app.replaceChildren(h("h1", {}, "Career sites"),
    h("p", { class: "muted" }, "Employers' own careers pages and official portals for Ireland, India, the UK and the rest of Europe. Apply on the employer's site; check each one's pages for graduate schemes and visa information."),
    h("div", { class: "card" }, h("div", { class: "row" }, search, h("button", { class: "btn primary", onclick: load }, "Search")), h("div", { class: "row" }, field("Country", countrySel), field("Type", catSel))), list);
  countrySel.onchange = catSel.onchange = load;
  try { await load(); } catch (x) { list.replaceChildren(h("p", { class: "err" }, x.message)); }
}

async function applicationsView() {
  $app.replaceChildren(h("h1", {}, "My applications"), h("p", { class: "muted" }, "Loading…"));
  const { applications } = await api("GET", "/api/applications");
  const rows = applications.map(a => {
    const status = h("select", {}, state.options.statuses.map(s => h("option", { value: s, selected: a.status === s }, s[0].toUpperCase() + s.slice(1))));
    const applied = h("input", { type: "date", value: a.applied_on || "" }), closing = h("input", { type: "date", value: a.closing_date || "" });
    const notes = h("textarea", { rows: 2 }); notes.value = a.notes || "";
    const save = h("button", { class: "btn", onclick: async () => { await api("POST", "/api/applications", { job_id: a.job_id, status: status.value, applied_on: applied.value, closing_date: closing.value, notes: notes.value }); save.textContent = "Saved"; setTimeout(() => save.textContent = "Save", 1200); } }, "Save");
    const del = h("button", { class: "btn danger", onclick: async () => { await api("DELETE", "/api/applications/" + a.job_id); applicationsView(); } }, "Remove");
    const overdue = a.closing_date && a.status === "saved" && a.closing_date < new Date().toISOString().slice(0, 10);
    return h("tr", {}, h("td", {}, h("strong", {}, a.job.title), h("div", { class: "muted small" }, `${a.job.company} · ${a.job.location}`),
        a.job.track ? h("div", { class: "small" }, "Domain: " + a.job.track + (a.job.cv ? " · CV: " + a.job.cv : "")) : "", a.job.url ? h("a", { href: a.job.url, target: "_blank", rel: "noopener noreferrer" }, "Open advert") : "", overdue ? h("div", { class: "err small" }, "Closing date has passed") : ""),
      h("td", {}, status), h("td", {}, h("label", {}, "Applied"), applied, h("label", {}, "Closes"), closing), h("td", {}, notes), h("td", {}, save, " ", del));
  });
  $app.replaceChildren(h("h1", {}, "My applications"), applications.length ? h("div", { class: "card", style: "overflow-x:auto" },
    h("table", {}, h("thead", {}, h("tr", {}, ["Job", "Status", "Dates", "Notes", ""].map(t => h("th", {}, t)))), h("tbody", {}, rows)))
    : h("p", { class: "muted" }, "Nothing tracked yet. Use “Apply on employer site” or the tracker menu on a matched job."));
}

function thresholdsView() {
  const t = state.me.thresholds;
  $app.replaceChildren(h("h1", {}, "Visa salary rules used"), h("p", { class: "muted" }, "Every matched job is checked against these minimums. The occupation's own going rate can be higher, so always confirm with the employer."),
    ...Object.entries(t).map(([c, v]) => h("div", { class: "card" }, h("h2", {}, `${state.options.countries[c] || c}: ${v.route}`),
      h("ul", { class: "plain" }, Object.entries(v.labels).map(([k, label]) => h("li", {}, `${label}: ${money(v.currency, v[k])}`))),
      h("p", { class: "small muted" }, `In force from ${v.as_of} · `, h("a", { href: v.source, target: "_blank", rel: "noopener noreferrer" }, "Official guidance")))));
}

function staticAccountView() {
  const msg = h("div", { class: "small" }); const err = h("div", { class: "err", role: "alert" });
  const exportBtn = h("button", { class: "btn primary", onclick: async () => { const b = await api("GET", "/api/export"); h("a", { href: URL.createObjectURL(b), download: "my-candidate-profile.json" }).click(); } }, "Download my data");
  const file = h("input", { type: "file", accept: ".json,application/json" });
  const importBtn = h("button", { class: "btn", onclick: async () => {
    err.textContent = ""; const f = file.files[0]; if (!f) { err.textContent = "Choose an exported .json file first."; return; }
    try { LocalApi.importData(JSON.parse(await f.text())); state.me = await api("GET", "/api/me"); state.jobs = null; state.view = "jobs"; render(); }
    catch (x) { err.textContent = x instanceof SyntaxError ? "That file isn't valid JSON." : x.message; }
  } }, "Import");
  const reset = h("button", { class: "btn danger", onclick: async () => { if (confirm("Delete your profile, CVs and tracked jobs from this browser?")) { await api("DELETE", "/api/account"); state.me = await api("GET", "/api/me"); state.jobs = null; state.view = "profile"; render(); } } }, "Clear everything in this browser");
  $app.replaceChildren(h("h1", {}, "Your data"),
    h("div", { class: "card" }, h("h2", {}, "Where it is"), h("p", {}, "Your profile, CV text and tracked jobs are stored only in this browser, on this device. The site has no accounts and sends nothing to a server, so clearing your browser data, or using another browser or device, starts you from scratch."),
      h("p", { class: "muted small" }, "Download a copy to keep, move to another device, or send to whoever is running the test.")),
    h("div", { class: "card" }, h("h2", {}, "Back up or move"), h("div", { class: "actions" }, exportBtn), h("label", {}, "Restore from a download"), file, h("div", { class: "actions" }, importBtn), err, msg),
    h("div", { class: "card" }, h("h2", {}, "Start again"), h("div", { class: "actions" }, reset)));
}

function accountView() {
  if (STATIC) return staticAccountView();
  const dl = h("button", { class: "btn", onclick: async () => { const b = await api("GET", "/api/export"); const a = h("a", { href: URL.createObjectURL(b), download: "my-data.json" }); a.click(); } }, "Download my data");
  const cv = "";
  const del = h("button", { class: "btn danger", onclick: async () => { if (confirm("Permanently delete your account, resume, profile and applications?")) { await api("DELETE", "/api/account"); state.me = null; render(); } } }, "Delete my account and data");
  const admin = h("div"); 
  const backup = h("button", { class: "btn", onclick: async () => { const b = await api("GET", "/api/admin/backup"); h("a", { href: URL.createObjectURL(b), download: "matcher-backup.sqlite3" }).click(); } }, "Download database backup");
  if (state.me.is_admin) api("GET", "/api/admin/candidates").then(d => admin.replaceChildren(h("h2", {}, "Candidates (admin)"), h("div", { class: "actions" }, backup),  h("table", {}, h("thead", {}, h("tr", {}, ["Email", "Joined", "Tracked", "Applied"].map(x => h("th", {}, x)))), h("tbody", {}, d.candidates.map(c => h("tr", {}, h("td", {}, c.email), h("td", {}, c.created_at.slice(0, 10)), h("td", {}, c.applications), h("td", {}, c.applied)))))));
  $app.replaceChildren(h("h1", {}, "Account"), h("div", { class: "card" }, h("p", {}, "Signed in as ", h("strong", {}, state.me.email)),
    h("p", { class: "muted small" }, "Your resume, visa details and preferences are visible only to you" + (state.me.is_admin ? " (admins see candidate email and application counts only)." : " and are used only to match jobs.")),
    h("div", { class: "actions" }, dl, cv, del)), admin);
}
boot();
