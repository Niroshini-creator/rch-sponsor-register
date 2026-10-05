(() => {
  const $ = (s) => document.querySelector(s);
  const form = $("#filters");
  const PAGE = 20;
  const COUNTRY = { GB: "United Kingdom", FR: "France" };
  const SPONS = { confirmed: ["Offers sponsorship", "ok"], licensed_sponsor: ["Licensed UK sponsor", "ok"],
                  permit_check: ["Work permit via employer", ""], unverified: ["Sponsorship not verified", "warn"],
                  agency: ["Agency: sponsor unknown", "warn"] };
  const VIEWS = [["all", "All matches"], ["GB", "United Kingdom"], ["FR", "France"], ["career", "Employer career sites"],
                 ["direct", "Direct employers"], ["near", "Closest matches"]];
  let data = { jobs: [], near_misses: [] }, view = "all", shown = PAGE;

  const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
  const safeUrl = (u) => (/^https?:\/\//i.test(u) ? u : "#");
  const ageDays = (iso) => (Date.now() - new Date(iso).getTime()) / 864e5;
  const ago = (iso) => { const d = ageDays(iso); return d < 1 ? "today" : d < 2 ? "yesterday" : `${Math.floor(d)} days ago`; };
  const salaryMax = (s) => { const m = (s || "").replace(/,/g, "").match(/\d{4,6}/g); return m ? Math.max(...m.map(Number)) : 0; };
  const minPay = (j) => { const p = (data.profile || {}).min_salary; return typeof p === "object" ? (p[j.country] || 0) : (p || 0); };
  const pool = () => (view === "near" ? data.near_misses || [] : data.jobs);

  function inView(j) {
    if (view === "GB" || view === "FR") return j.country === view;
    if (view === "career") return j.channel === "career_site";
    if (view === "direct") return !j.agency;
    return true;
  }

  function matches(j, f, skipView) {
    const q = (f.get("q") || "").toLowerCase().trim();
    const checked = (name) => f.getAll(name);
    return (skipView || inView(j)) &&
      ageDays(j.posted_at) <= Math.min(+f.get("days"), 7) &&
      (view === "near" || j.match >= +f.get("min")) &&
      (!f.get("country") || j.country === f.get("country")) &&
      checked("channel").includes(j.channel) &&
      checked("spons").includes(j.sponsorship) &&
      (!f.get("direct") || !j.agency) && (!f.get("english") || j.english) &&
      (!f.get("paid") || salaryMax(j.salary) >= minPay(j)) &&
      (!f.get("source") || j.source === f.get("source")) &&
      (!q || `${j.title} ${j.company} ${j.location} ${(j.matched_keywords || []).join(" ")}`.toLowerCase().includes(q));
  }

  function rows() {
    const f = new FormData(form), list = pool().filter((j) => matches(j, f));
    return $("#sort").value === "newest"
      ? list.sort((a, b) => b.posted_at.localeCompare(a.posted_at))
      : list.sort((a, b) => b.match - a.match || b.posted_at.localeCompare(a.posted_at));
  }

  function card(j) {
    const tone = j.match >= 75 ? "good" : j.match >= 55 ? "mid" : "low";
    const tags = el("div", { className: "tags" });
    const [label, kind] = SPONS[j.sponsorship] || ["", ""];
    if (label) tags.append(el("span", { className: `tag ${kind}`, textContent: label }));
    tags.append(el("span", { className: j.channel === "career_site" ? "tag direct" : "tag", textContent: j.channel === "career_site" ? "Employer careers site" : "Job board" }));
    tags.append(el("span", { className: "tag", textContent: j.source }));
    if (j.contract) tags.append(el("span", { className: "tag", textContent: j.contract }));
    if (j.english === false) tags.append(el("span", { className: "tag warn", textContent: "May need another language" }));
    for (const fl of j.flags || []) if (fl !== "Recruitment agency advert") tags.append(el("span", { className: "tag warn", textContent: fl }));
    const pay = j.salary ? ` · ${j.currency || ""}${j.salary}` : "";
    return el("li", { className: "job" },
      el("div", { className: "job-head" },
        el("h2", {}, el("a", { href: safeUrl(j.url), target: "_blank", rel: "noopener noreferrer", textContent: j.title })),
        el("div", { className: "right" }, el("span", { className: `match ${tone}`, title: "Match against the CV" }, `${j.match}%`, el("small", { textContent: "match" })),
          el("span", { className: "posted", textContent: ago(j.posted_at) }))),
      el("p", { className: "employer" }, el("strong", { textContent: j.company })),
      el("p", { className: "meta", textContent: `${j.location} · ${COUNTRY[j.country] || j.country}${pay}` }),
      tags,
      el("p", { className: "desc", textContent: j.description }),
      el("div", { className: "job-foot" },
        el("details", { className: "why" }, el("summary", { textContent: "Why this score" }),
          el("div", { textContent: (j.reasons || []).join(" · ") }),
          el("div", { textContent: (j.matched_keywords || []).length ? `Matched: ${j.matched_keywords.join(", ")}` : "" })),
        el("a", { className: "btn", href: safeUrl(j.url), target: "_blank", rel: "noopener noreferrer", textContent: j.channel === "career_site" ? "Apply on careers site" : "View & apply" })));
  }

  function render() {
    $("#min-out").textContent = `${form.min.value}%`;
    const list = rows();
    $("#summary").textContent = view === "near"
      ? `${list.length} closest matches (below the ${form.min.value}% threshold, probably not a fit)`
      : `${list.length} matching role${list.length === 1 ? "" : "s"} of ${data.jobs.length} found in the last ${data.window_days || 7} days`;
    const slice = list.slice(0, shown);
    $("#jobs").replaceChildren(...(slice.length ? slice.map(card) : [el("li", { className: "notice",
      textContent: pool().length ? "No roles match these filters. Lower the minimum match or widen the date range, or try Closest matches."
        : "No roles yet. The feed fills after the first daily run; see Data sources below." })]));
    $("#more").hidden = list.length <= shown;
    renderViews(); renderStats(list); renderCounts();
  }

  function renderViews() {
    const f = new FormData(form), saved = view;
    $("#views").replaceChildren(...VIEWS.map(([key, label]) => {
      view = key; const n = pool().filter((j) => matches(j, f)).length; view = saved;
      return el("button", { type: "button", className: `view${key === saved ? " active" : ""}`, onclick: () => { view = key; shown = PAGE; render(); } },
        label, el("span", { className: "count", textContent: String(n) }));
    }));
  }

  function renderStats(list) {
    const best = list.reduce((m, j) => Math.max(m, j.match), 0);
    const tile = (v, l) => el("div", { className: "stat" }, el("span", { className: "stat-value", textContent: String(v) }), el("span", { className: "stat-label", textContent: l }));
    $("#stats").replaceChildren(tile(list.length, "Roles shown"), tile(best ? `${best}%` : "–", "Best match"),
      tile(list.filter((j) => j.country === "GB").length, "United Kingdom"), tile(list.filter((j) => j.country === "FR").length, "France"),
      tile(list.filter((j) => !j.agency).length, "Direct employers"));
  }

  function renderCounts() {
    const f = new FormData(form);
    const base = pool().filter((j) => matches(j, f));
    document.querySelectorAll("[data-count]").forEach((n) => {
      const [k, v] = n.dataset.count.split(":");
      n.textContent = String(base.filter((j) => (k === "channel" ? j.channel : j.sponsorship) === v).length);
    });
  }

  function csv() {
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""').replace(/^([=+\-@])/, "'$1")}"`;
    const head = ["Match %", "Title", "Company", "Location", "Country", "Salary", "Sponsorship", "Apply via", "Source", "Posted", "URL"];
    const lines = rows().map((j) => [j.match, j.title, j.company, j.location, j.country, `${j.currency || ""}${j.salary || ""}`, j.sponsorship,
      j.channel, j.source, j.posted_at.slice(0, 10), j.url].map(esc).join(","));
    const a = el("a", { href: URL.createObjectURL(new Blob([[head.join(","), ...lines].join("\n")], { type: "text/csv" })), download: "matched-roles.csv" });
    a.click(); URL.revokeObjectURL(a.href);
  }

  function showStatic() {
    const p = data.profile || {};
    const pay = typeof p.min_salary === "object" ? Object.entries(p.min_salary).map(([c, v]) => `${c === "FR" ? "€" : "£"}${v.toLocaleString()}+ (${c})`).join(" · ") : `£${(p.min_salary || 0).toLocaleString()}+`;
    $("#tagline").textContent = `${p.name || "Candidate"}: ${p.headline || ""}`;
    $("#chips").replaceChildren(...[`Expects ${pay}`, p.notice_period_days && `${p.notice_period_days}-day notice`, p.clearance && `Clearance: ${p.clearance}`,
      p.driving_licence && `${p.driving_licence} driving licence`].filter(Boolean).map((t) => el("span", { className: "tag", textContent: t })));
    if (p.min_match != null) form.min.value = p.min_match;
    form.country.append(...(p.countries || ["GB", "FR"]).map((c) => el("option", { value: c, textContent: COUNTRY[c] || c })));
    const names = [...new Set([...data.jobs, ...(data.near_misses || [])].map((j) => j.source))].sort();
    form.source.append(...names.map((s) => el("option", { value: s, textContent: s })));
    const updated = $("#updated");
    if (data.generated_at) {
      const hrs = (Date.now() - new Date(data.generated_at)) / 36e5;
      updated.textContent = `Updated ${new Date(data.generated_at).toLocaleString()} · refreshed daily`;
      updated.classList.toggle("stale", hrs > 36);
    } else updated.textContent = "Not yet generated";
    const c = data.counts || {};
    const head = el("tr", {}, ...["Source", "Status", "Detail"].map((t) => el("th", { textContent: t })));
    const body = Object.entries(data.sources || {}).map(([n, s]) => el("tr", {}, el("td", { textContent: n }),
      el("td", {}, el("span", { className: `dot ${s.status}` }), s.status), el("td", { textContent: String(s.count ?? s.reason ?? s.error ?? "") })));
    $("#sources").replaceChildren(head, ...body, el("tr", {}, el("td", { colSpan: 3, className: "fineprint",
      textContent: `Fetched ${c.fetched ?? 0} · removed ${c.clearance_removed ?? 0} needing clearance, ${c.no_sponsorship_removed ?? 0} refusing sponsorship, ${c.language_removed ?? 0} needing French · ${c.below_threshold ?? 0} below threshold · ${c.full_advert_fetched ?? 0} full adverts read · published ${c.published ?? 0}` })));
  }

  form.addEventListener("input", () => { shown = PAGE; render(); });
  form.addEventListener("reset", () => setTimeout(() => { form.min.value = (data.profile || {}).min_match ?? 45; shown = PAGE; render(); }));
  $("#sort").addEventListener("change", render);
  $("#more").addEventListener("click", () => { shown += PAGE; render(); });
  $("#export").addEventListener("click", csv);
  document.querySelectorAll("[data-dialog]").forEach((b) => b.addEventListener("click", () => document.getElementById(b.dataset.dialog).showModal()));
  fetch(`data/jobs.json?_=${Date.now()}`).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => { data = d; showStatic(); render(); })
    .catch(() => { $("#updated").textContent = "Feed not available yet"; render(); });
})();
