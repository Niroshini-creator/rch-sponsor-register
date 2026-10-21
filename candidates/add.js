"use strict";
/* Add-candidate view: reads the CVs in this browser (pdf.js, vendored under /matcher), runs intake.js, lets the recruiter correct
 * tiers, then offers the profile.json to commit. Nothing is uploaded. Mounted by app.js into the #add-tpl form; the finished profile goes to onProfile(). */
function mountAdd(h, onProfile) {
  const $ = id => document.getElementById(id);
  const fileText = DocRead.fileText;

  // ------------------------------------------------------------------ role families (the same file the Python scan reads)
  const getJson = url => fetch(url, { cache: "no-cache" }).then(r => { if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`); return r.json(); });
  const ready = Promise.all([getJson("../candidateboard/roles.json"), getJson("../candidateboard/regions.json")])
    .then(([roles, regions]) => CandidateIntake.init(roles, regions));

  // ------------------------------------------------------------------ form
  function cvRow(track = "") {
    const row = h("div", { class: "bar", style: "margin-bottom:8px" },
      h("label", {}, "Name this CV", h("input", { class: "track", value: track, placeholder: "optional, e.g. Business Analyst" })),
      h("label", {}, "CV file", h("input", { class: "file", type: "file", accept: ".pdf,.docx,.txt,.md", required: true })),
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
  // Attach a document of suitable positions (PDF, Word or text): read here, shown as a preview, and editable in the box below.
  const preview = () => {
    const list = CandidateIntake.parseRoleList($("roles-text").value), by = new Map();
    for (const r of list) by.set(r.section || "", [...(by.get(r.section || "") || []), r.title]);
    const domains = list.length < 2 ? CandidateIntake.documentDomains($("roles-text").value) : [], labels = CandidateIntake.labels();
    if (domains.length) { $("roles-preview").replaceChildren(h("b", {}, "No job titles found, so its keywords were read"), h("div", {}, "Searching these kinds of role: ", domains.map(k => labels[k].label).join(" · "))); return; }
    $("roles-preview").replaceChildren(...(list.length ? [h("b", {}, `${list.length} position${list.length === 1 ? "" : "s"} found`),
      ...[...by].map(([sec, titles]) => h("div", {}, sec ? h("span", { class: "muted" }, sec + ": ") : null, titles.join(" · ")))] : []));
  };
  $("roles-text").addEventListener("input", preview);
  $("roles-file").onchange = async e => {
    const f = e.target.files[0];
    if (!f) return;
    $("msg").textContent = "Reading…";
    try {
      await ready;
      $("roles-text").value = await fileText(f); preview();
      $("msg").textContent = CandidateIntake.parseRoleList($("roles-text").value).length ? "" : `Read ${f.name} but found no job titles in it. Check the text below.`;
    } catch (err) { $("msg").textContent = err.message; }
  };

  // Holding OPT or Stamp 1G means the candidate wants that country: tick it so its roles are searched.
  const tick = (box, region) => $(box).addEventListener("change", e => { if (e.target.checked) document.querySelector(`input[name=region][value=${region}]`).checked = true; });
  tick("right-opt", "US"); tick("right-1g", "IE");

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
        regions: [...document.querySelectorAll('input[name=region]:checked')].map(el => el.value), englishOnly: $("english-only").checked, extraRoles: wanted, indiaMinLpa: Number($("india-lpa").value) || 0, experienceLevel: $("level").value,
      clearance: $("clearance").value, drivingLicence: licence === "" ? null : licence === "yes",
        visa: { type, label, expires: $("expires").value, sponsorship: $("sponsorship").value, new_entrant: $("new-entrant").checked,
          work_rights: [$("right-opt").checked ? "us_opt" : "", $("right-1g").checked ? "ie_stamp_1g" : ""].filter(Boolean) },
      });
      $("msg").textContent = "";
      if (!profile.roles.length && !profile.also_consider.length) throw new Error("Could not find skills or job titles in this CV. Check it is a text-based PDF, or paste a list of the roles you want under Optional.");
      onProfile(profile);
    } catch (err) { $("msg").textContent = err.message; }
  };
}
