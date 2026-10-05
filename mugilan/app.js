(() => {
  const $ = (s) => document.querySelector(s);
  const form = $("#filters"), results = $("#results");
  const SPONS = { confirmed: ["Advert offers sponsorship", "ok"], licensed_sponsor: ["Licensed sponsor", "ok"],
                  unverified: ["Sponsorship not verified", "warn"], agency: ["Agency: sponsor unknown", "warn"] };
  let data = { jobs: [] };

  const el = (tag, props = {}, ...kids) => {
    const n = Object.assign(document.createElement(tag), props);
    for (const k of kids) n.append(k);
    return n;
  };
  const safeUrl = (u) => (/^https?:\/\//i.test(u) ? u : "#");
  const ageDays = (iso) => (Date.now() - new Date(iso).getTime()) / 864e5;
  const ago = (iso) => { const d = ageDays(iso); return d < 1 ? "today" : d < 2 ? "yesterday" : `${Math.floor(d)} days ago`; };
  const salaryMax = (s) => { const m = (s || "").replace(/,/g, "").match(/\d{4,6}/g); return m ? Math.max(...m.map(Number)) : 0; };

  function filtered() {
    const f = new FormData(form), q = (f.get("q") || "").toLowerCase().trim();
    const min = +f.get("min"), days = +f.get("days"), spons = f.get("spons"), source = f.get("source");
    const minPay = (data.profile || {}).min_salary || 60000;
    return data.jobs.filter((j) =>
      ageDays(j.posted_at) <= Math.min(days, 7) && j.match >= min &&
      (!spons || j.sponsorship === spons) && (!source || j.source === source) &&
      (!f.get("paid") || salaryMax(j.salary) >= minPay) &&
      (!q || `${j.title} ${j.company} ${j.location} ${(j.matched_keywords || []).join(" ")}`.toLowerCase().includes(q)));
  }

  function card(j) {
    const tone = j.match >= 75 ? "good" : j.match >= 55 ? "mid" : "low";
    const tags = el("div", { className: "tags" });
    const [label, kind] = SPONS[j.sponsorship] || ["", ""];
    if (label) tags.append(el("span", { className: `tag ${kind}`, textContent: label }));
    if (j.salary) tags.append(el("span", { className: "tag", textContent: `£${j.salary}` }));
    if (j.contract) tags.append(el("span", { className: "tag", textContent: j.contract }));
    for (const fl of j.flags || []) if (fl !== "Recruitment agency advert") tags.append(el("span", { className: "tag warn", textContent: fl }));
    const link = el("a", { href: safeUrl(j.url), target: "_blank", rel: "noopener noreferrer", textContent: j.title });
    const why = el("details", { className: "why" }, el("summary", { textContent: "Why this score" }),
      el("div", { textContent: (j.reasons || []).join(" · ") }),
      el("div", { textContent: (j.matched_keywords || []).length ? `Matched: ${j.matched_keywords.join(", ")}` : "" }));
    return el("article", { className: "card" },
      el("div", { className: `pct ${tone}`, textContent: `${j.match}%` }, el("small", { textContent: "match" })),
      el("div", {},
        el("h2", {}, link),
        el("div", { className: "meta", textContent: `${j.company} · ${j.location} · ${j.source} · posted ${ago(j.posted_at)}` }),
        el("p", { className: "desc", textContent: j.description }), tags, why));
  }

  function render() {
    $("#min-out").textContent = `${form.min.value}%`;
    const rows = filtered();
    $("#count").textContent = `${rows.length} matching role${rows.length === 1 ? "" : "s"} (of ${data.jobs.length} found in the last ${data.window_days || 7} days)`;
    results.replaceChildren(...(rows.length ? rows.map(card) : [el("div", { className: "empty",
      textContent: data.jobs.length ? "No roles match these filters. Lower the minimum match or widen the date range."
        : "No matched roles yet. The feed fills after the first daily run (see Data sources below)." })]));
  }

  function csv() {
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""').replace(/^([=+\-@])/, "'$1")}"`;
    const head = ["Match %", "Title", "Company", "Location", "Salary", "Sponsorship", "Source", "Posted", "URL"];
    const lines = filtered().map((j) => [j.match, j.title, j.company, j.location, j.salary, j.sponsorship, j.source, j.posted_at.slice(0, 10), j.url].map(esc).join(","));
    const a = el("a", { href: URL.createObjectURL(new Blob([[head.join(","), ...lines].join("\n")], { type: "text/csv" })), download: "matched-roles.csv" });
    a.click(); URL.revokeObjectURL(a.href);
  }

  function showStatic() {
    const p = data.profile || {};
    $("#who").textContent = p.name || "the candidate";
    $("#headline").textContent = p.headline || "";
    $("#profile").replaceChildren(...[
      p.min_salary && `Expects £${p.min_salary.toLocaleString()}+`, p.notice_period_days && `${p.notice_period_days}-day notice`,
      p.visa, p.clearance && `Clearance: ${p.clearance}`, p.driving_licence && `${p.driving_licence} driving licence`,
    ].filter(Boolean).map((t) => el("span", { className: "chip", textContent: t })));
    if (p.min_match != null) { form.min.value = p.min_match; }
    const sources = [...new Set(data.jobs.map((j) => j.source))].sort();
    form.source.append(...sources.map((s) => el("option", { value: s, textContent: s })));
    $("#updated").textContent = data.generated_at ? `Updated ${new Date(data.generated_at).toLocaleString()} · refreshed daily` : "Not yet generated";
    const rows = Object.entries(data.sources || {}).map(([n, s]) => el("tr", {},
      el("td", { textContent: n }), el("td", { textContent: s.status }), el("td", { textContent: String(s.count ?? s.reason ?? s.error ?? "") })));
    const c = data.counts || {};
    $("#sources").replaceChildren(el("table", {}, ...rows),
      el("p", { className: "meta", textContent: `Fetched ${c.fetched ?? 0} · removed ${c.clearance_removed ?? 0} needing clearance, ${c.no_sponsorship_removed ?? 0} refusing sponsorship, ${c.below_threshold ?? 0} below threshold · published ${c.published ?? 0}` }));
  }

  form.addEventListener("input", render);
  form.addEventListener("submit", (e) => e.preventDefault());
  $("#csv").addEventListener("click", csv);
  fetch(`data/jobs.json?_=${Date.now()}`).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => { data = d; showStatic(); render(); })
    .catch(() => { $("#updated").textContent = "Feed not available yet"; render(); });
})();
