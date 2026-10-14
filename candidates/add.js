"use strict";
/* Add-candidate view: reads the CVs in this browser (pdf.js, vendored under /matcher), runs intake.js, lets the recruiter correct
 * tiers, then offers the profile.json to commit. Nothing is uploaded. Mounted by app.js into the #add-tpl form. */
function mountAdd(h) {
  const $ = id => document.getElementById(id);
  // ------------------------------------------------------------------ reading files
  let pdfLib = null;
  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    return pdfLib || (pdfLib = new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = "../matcher/vendor/pdfjs/pdf.min.js";
      el.onload = () => { window.pdfjsLib.GlobalWorkerOptions.workerSrc = "../matcher/vendor/pdfjs/pdf.worker.min.js"; resolve(window.pdfjsLib); };
      el.onerror = () => reject(new Error("The PDF reader could not be loaded"));
      document.head.appendChild(el);
    }));
  }
  async function pdfText(bytes) {
    const doc = await (await loadPdfJs()).getDocument({ data: bytes }).promise;
    const pages = [];
    for (let i = 1; i <= Math.min(doc.numPages, 20); i++) {
      const content = await (await doc.getPage(i)).getTextContent();
      pages.push(content.items.filter(it => typeof it.str === "string").map(it => it.str + (it.hasEOL ? "\n" : " ")).join(""));
    }
    return pages.join("\n").replace(/[ \t]+/g, " ").replace(/ ?\n ?/g, "\n").trim();
  }
  async function fileText(file) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const text = /\.pdf$/i.test(file.name) ? await pdfText(bytes) : new TextDecoder().decode(bytes);
    if (text.length < 30) throw new Error(`${file.name}: no readable text (a scanned PDF is only pictures). Upload a text-based PDF or paste the text into a .txt file.`);
    return text;
  }

  // ------------------------------------------------------------------ role families (the same file the Python scan reads)
  const ready = fetch("../candidateboard/roles.json", { cache: "no-cache" }).then(r => { if (!r.ok) throw new Error(`roles.json: HTTP ${r.status}`); return r.json(); })
    .then(roles => CandidateIntake.init(roles));

  // ------------------------------------------------------------------ form
  function cvRow(track = "") {
    const row = h("div", { class: "bar", style: "margin-bottom:8px" },
      h("label", {}, "Track name", h("input", { class: "track", value: track, placeholder: "e.g. Business Analyst", required: true })),
      h("label", {}, "CV file", h("input", { class: "file", type: "file", accept: ".pdf,.txt,.md", required: true })),
      h("button", { type: "button", class: "btn", onclick: () => { if ($("cvs").children.length > 1) row.remove(); } }, "Remove"));
    return row;
  }
  $("cvs").append(cvRow());
  $("add-cv").onclick = () => $("cvs").append(cvRow());
  $("roles-file").onchange = async e => {
    const f = e.target.files[0];
    if (!f) return;
    try { $("roles-text").value = /\.pdf$/i.test(f.name) ? await pdfText(new Uint8Array(await f.arrayBuffer())) : await f.text(); }
    catch (err) { $("msg").textContent = err.message; }
  };

  $("form").onsubmit = async e => {
    e.preventDefault();
    $("msg").textContent = "Reading…"; $("result").replaceChildren();
    try {
      await ready;
      const rows = [...$("cvs").children], cvs = [];
      for (const r of rows) {
        const track = r.querySelector(".track").value.trim(), file = r.querySelector(".file").files[0];
        cvs.push({ track, filename: file.name, text: await fileText(file) });
      }
      if (new Set(cvs.map(c => c.track)).size !== cvs.length) throw new Error("Each CV needs a different track name.");
      const [type, label] = $("visa").value.split("|");
      const licence = $("licence").value;
      const profile = CandidateIntake.buildProfile(cvs, $("roles-text").value, {
        name: $("name").value.trim(), location: $("location").value.trim(), status: $("status").value.trim(), notes: $("notes").value.trim(),
        clearance: $("clearance").value, drivingLicence: licence === "" ? null : licence === "yes",
        visa: { type, label, expires: $("expires").value, sponsorship: $("sponsorship").value, new_entrant: $("new-entrant").checked },
      });
      $("msg").textContent = "";
      showResult(profile);
    } catch (err) { $("msg").textContent = err.message; }
  };

  // ------------------------------------------------------------------ result
  function showResult(p) {
    const labels = CandidateIntake.labels();
    const warnings = [];
    if (!p.name) warnings.push("No name found in the CV: type one into the name box and scan again.");
    if (!p.roles.length) warnings.push("No target roles found. Paste a suitable-roles list, or the CV has too few recognised skills.");
    if (!p.experience_years) warnings.push("No dated roles found (expected e.g. “Apr 2022 – Sep 2024”), so experience is 0 years and senior titles are not flagged.");
    if (!p.visa.expires) warnings.push("Visa expiry not set.");
    const slug = h("input", { value: p.slug, size: 28 });
    slug.oninput = () => { p.slug = CandidateIntake.slugify(slug.value); };
    const tierBlock = t => {
      const rows = p.roles.filter(r => r.tier === t);
      return h("div", { class: "panel" }, h("h2", {}, ["", "Tier 1 · Core (apply first)", "Tier 2 · Close to the CV", "Tier 3 · Stretch"][t]),
        rows.length ? h("table", {}, rows.map(r => h("tr", {},
          h("td", {}, r.title, h("div", { class: "muted small" }, `${labels[r.family]?.label || "No family"} · ${r.track}${r.source !== "recruiter list" ? " · suggested" : ""}`)),
          h("td", {}, h("select", { onchange: e => { r.tier = Number(e.target.value); showResult(p); } }, [1, 2, 3].map(n => h("option", { value: n, ...(n === r.tier ? { selected: true } : {}) }, `Tier ${n}`)))),
          h("td", {}, h("button", { type: "button", class: "btn", onclick: () => { p.roles.splice(p.roles.indexOf(r), 1); showResult(p); } }, "×"))))) : h("p", { class: "muted small" }, "None"));
    };
    const json = JSON.stringify(p, null, 1) + "\n";
    const repo = location.hostname.endsWith(".github.io") ? `https://github.com/${location.hostname.split(".")[0]}/${location.pathname.split("/")[1]}` : "";
    const dl = () => { const a = h("a", { href: URL.createObjectURL(new Blob([json], { type: "application/json" })), download: `${p.slug}.json` }); document.body.append(a); a.click(); a.remove(); };
    $("result").replaceChildren(
      h("div", { class: "panel" }, h("h2", {}, `${p.name || "Unnamed"} · ${p.experience_years} years · ${p.education || "education not found"}`),
        h("p", { class: "muted small" }, p.headline), ...warnings.map(w => h("p", { class: "small" }, h("span", { class: "badge warn" }, w)))),
      h("div", { class: "grid2" }, tierBlock(1), tierBlock(2), tierBlock(3)),
      h("div", { class: "panel" }, h("h2", {}, "Other roles worth a look"),
        h("ul", { class: "chips" }, p.also_consider.map(k => h("li", { class: `chip ${labels[k].sponsor === "rare" ? "warn" : ""}` }, labels[k].label))),
        h("p", { class: "small muted" }, "Shown only at employers that can sponsor. Amber ones are usually below the Skilled Worker skill level."),
        h("details", {}, h("summary", { class: "small" }, "Skills that will be matched against adverts"),
          p.tracks.map(t => h("div", {}, h("h3", {}, `${t.name} CV`), h("ul", { class: "chips" }, t.skills.map(s => h("li", { class: "chip" }, s.replace(/\[sz\]/g, "s").replace(/[\\?]/g, ""))))))) ),
      h("div", { class: "panel" }, h("h2", {}, "Save it"),
        h("p", { class: "bar" }, h("label", {}, "File name", slug), h("button", { type: "button", class: "btn", onclick: dl }, "Download profile"),
          h("button", { type: "button", class: "btn", onclick: async e => { await navigator.clipboard.writeText(json); e.target.textContent = "Copied"; } }, "Copy JSON")),
        h("ol", { class: "small" },
          h("li", {}, "Put the file at ", h("code", {}, `candidates/profiles/${p.slug}.json`), " in the repository",
            repo ? [" (", h("a", { href: `${repo}/new/main/candidates/profiles?filename=${encodeURIComponent(p.slug)}.json`, target: "_blank", rel: "noopener" }, "create it on GitHub"), ", paste the copied JSON)"] : "."),
          h("li", {}, "Pushing it to the main branch runs the “Refresh candidate boards” workflow, which builds the board; it then opens at ", h("code", {}, `/candidates/?c=${p.slug}`), ".")),
        h("p", { class: "small muted" }, "The profile holds the name, headline, visa, skills and roles. No phone, email or CV file. If the repository is public, anyone with the board link can read it.")));
  }
}
