/* The employer's own careers site for a vacancy that was found on a job board (Adzuna links do not open everywhere).
 * Sources: config/career_pages.json (curated home pages, take priority) and config/employers.json (every employer the feed
 * reads directly: the board address is derived from its job-site system). Company names are compared as jobfeed.text.normalise_company. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./match.js").normaliseCompany);
  else root.CandidateCareers = factory((c) => root.CandidateMatch.normaliseCompany(c));
})(typeof self !== "undefined" ? self : this, function (norm) {
  "use strict";
  const BOARD = {
    workday: e => e.host && e.site && `https://${e.host}/${e.site}`,
    greenhouse: e => e.id && `https://boards.greenhouse.io/${e.id}`,
    lever: e => e.id && `https://jobs${e.region === "eu" ? ".eu" : ""}.lever.co/${e.id}`,
    ashby: e => e.id && `https://jobs.ashbyhq.com/${e.id}`,
    smartrecruiters: e => e.id && `https://jobs.smartrecruiters.com/${e.id}`,
    workable: e => e.id && `https://apply.workable.com/${e.id}`,
    recruitee: e => e.id && `https://${e.id}.recruitee.com`,
    oracle: e => e.host && e.site && `https://${e.host}/hcmUI/CandidateExperience/en/sites/${e.site}`,
    successfactors: e => e.host && `https://${e.host}`,
    teamtailor: e => e.host && `https://${e.host}`,
  };
  /** pages: career_pages.json; employers: employers.json. Returns company name -> careers URL ("" when unknown). */
  function build(pages, employers) {
    const map = new Map();
    const add = (names, url) => { for (const n of names) { const k = norm(n); if (k && url && !map.has(k)) map.set(k, url); } };
    for (const c of (pages && pages.companies) || []) add([c.name, ...(c.aliases || [])], c.url);
    for (const e of (employers && employers.employers) || []) {
      if (e.enabled === false) continue;
      const make = BOARD[(e.ats || "").toLowerCase()];
      if (make) add([e.name, e.register_name || ""], make(e));
    }
    return company => {
      const k = norm(company);
      if (!k) return "";
      if (map.has(k)) return map.get(k);
      for (const [m, url] of map) if (k.startsWith(m + " ")) return url;   // "Barclays Bank UK PLC" -> Barclays
      // Public-sector employers all advertise on one official board, whatever their own site looks like.
      if (/\bnhs\b/i.test(company)) return "https://www.jobs.nhs.uk/";
      if (/\buniversity\b|\bcollege\b/i.test(company) && !/\bhospitals?\b/i.test(company)) return "https://www.jobs.ac.uk/";
      return "";
    };
  }
  return { build };
});
