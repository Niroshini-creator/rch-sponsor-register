"use strict";
/* Add-candidate view: reads the CVs in this browser (pdf.js, vendored under /matcher), runs intake.js, lets the recruiter correct
 * tiers, then offers the profile.json to commit. Nothing is uploaded. Mounted by app.js into the #add-tpl form; the finished profile goes to onProfile(). */
function mountAdd(h, onProfile) {
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
  const getJson = url => fetch(url, { cache: "no-cache" }).then(r => { if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`); return r.json(); });
  const ready = Promise.all([getJson("../candidateboard/roles.json"), getJson("../candidateboard/regions.json")])
    .then(([roles, regions]) => CandidateIntake.init(roles, regions));

  // ------------------------------------------------------------------ form
  function cvRow(track = "") {
    const row = h("div", { class: "bar", style: "margin-bottom:8px" },
      h("label", {}, "Name this CV", h("input", { class: "track", value: track, placeholder: "optional, e.g. Business Analyst" })),
      h("label", {}, "CV file", h("input", { class: "file", type: "file", accept: ".pdf,.txt,.md", required: true })),
      h("button", { type: "button", class: "btn", onclick: () => { if ($("cvs").children.length > 1) row.remove(); } }, "Remove"));
    return row;
  }
  $("cvs").append(cvRow());
  $("add-cv").onclick = () => $("cvs").append(cvRow());

  // Roles the candidate wants: type a title and press Enter or Add; suggestions come from the role list.
  const wanted = [];
  const drawRoles = () => $("role-chips").replaceChildren(...wanted.map(t => h("li", { class: "chip info" }, t, " ",
    h("button", { type: "button", class: "btn", style: "padding:0 6px;margin-left:4px", "aria-label": `Remove ${t}`, onclick: () => { wanted.splice(wanted.indexOf(t), 1); drawRoles(); } }, "×"))));
  const addWanted = () => {
    const merged = CandidateIntake.cleanTitles([...wanted, ...$("role-input").value.split(/[,\n;]/)]);
    wanted.splice(0, wanted.length, ...merged);
    $("role-input").value = ""; drawRoles();
  };
  $("role-add").onclick = addWanted;
  $("role-input").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); addWanted(); } });
  ready.then(() => $("role-suggestions").replaceChildren(...CandidateIntake.suggestions().map(t => h("option", { value: t })))).catch(() => {});
  $("roles-file").onchange = async e => {
    const f = e.target.files[0];
    if (!f) return;
    try { $("roles-text").value = /\.pdf$/i.test(f.name) ? await pdfText(new Uint8Array(await f.arrayBuffer())) : await f.text(); }
    catch (err) { $("msg").textContent = err.message; }
  };

  $("form").onsubmit = async e => {
    e.preventDefault();
    $("msg").textContent = "Reading…";
    try {
      await ready;
      addWanted();                                  // a title typed but not yet added still counts
      const rows = [...$("cvs").children], cvs = [];
      for (const r of rows) {
        const track = r.querySelector(".track").value.trim(), file = r.querySelector(".file").files[0];
        cvs.push({ track: track || file.name.replace(/\.[^.]+$/, ""), filename: file.name, text: await fileText(file) });
      }
      if (new Set(cvs.map(c => c.track)).size !== cvs.length) throw new Error("Give each CV a different name.");
      const [type, label] = $("visa").value.split("|");
      const licence = $("licence").value;
    if (!document.querySelector('input[name=region]:checked')) throw new Error("Tick at least one place you would work.");
      const profile = CandidateIntake.buildProfile(cvs, $("roles-text").value, {
        name: $("name").value.trim(), location: $("location").value.trim(), status: $("status").value.trim(), notes: $("notes").value.trim(),
        regions: [...document.querySelectorAll('input[name=region]:checked')].map(el => el.value), englishOnly: $("english-only").checked, extraRoles: wanted,
      clearance: $("clearance").value, drivingLicence: licence === "" ? null : licence === "yes",
        visa: { type, label, expires: $("expires").value, sponsorship: $("sponsorship").value, new_entrant: $("new-entrant").checked },
      });
      $("msg").textContent = "";
      if (!profile.roles.length && !profile.also_consider.length) throw new Error("Could not find skills or job titles in this CV. Check it is a text-based PDF, or paste a list of the roles you want under Optional.");
      onProfile(profile);
    } catch (err) { $("msg").textContent = err.message; }
  };
}
