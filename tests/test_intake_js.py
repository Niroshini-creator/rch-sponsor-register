"""The browser scan (candidates/intake.js) must produce the same profile as the Python scan for the same CV text."""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from candidateboard import intake
from tests_fixtures import BA_CV, ROLES, SAP_CV

ROOT = Path(__file__).resolve().parent.parent
RUNNER = """
const fs = require('fs'); const [dir, out] = process.argv.slice(1);
const I = require(process.env.ROOT + '/candidates/intake.js').init(JSON.parse(fs.readFileSync(process.env.ROOT + '/candidateboard/roles.json', 'utf8')), JSON.parse(fs.readFileSync(process.env.ROOT + '/candidateboard/regions.json', 'utf8')));
const t = n => fs.readFileSync(dir + '/' + n, 'utf8');
const p = I.buildProfile([{track: 'SAP Security & GRC', filename: 'sap.txt', text: t('sap.txt')}, {track: 'Business Analyst', filename: 'ba.txt', text: t('ba.txt')}], t('roles.txt'),
  {name: 'Jane Example', slug: 'jane', location: 'Coventry', today: new Date(2026, 9, 14), clearance: 'none', drivingLicence: null,
   regions: ['GB', 'EU', 'AU', 'ME'], englishOnly: false,
   visa: {type: 'graduate', label: 'Graduate visa', expires: '2027-11', sponsorship: 'preferred', new_entrant: true}});
fs.writeFileSync(out, JSON.stringify(p));
"""


@unittest.skipUnless(shutil.which("node"), "node is needed to run the browser scan")
class ParityTests(unittest.TestCase):
    def test_same_profile_from_python_and_browser_scan(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, text in (("sap.txt", SAP_CV), ("ba.txt", BA_CV), ("roles.txt", ROLES)):
                (d / name).write_text(text, encoding="utf-8")
            py = intake.build_profile({"SAP Security & GRC": d / "sap.txt", "Business Analyst": d / "ba.txt"}, ROLES, name="Jane Example",
                                      slug="jane", location="Coventry", today=date(2026, 10, 14), regions=["GB", "EU", "AU", "ME"], english_only=False,
                                      visa={"type": "graduate", "label": "Graduate visa", "expires": "2027-11", "sponsorship": "preferred", "new_entrant": True})
            subprocess.run(["node", "-e", RUNNER, str(d), str(d / "js.json")], check=True, env={"ROOT": str(ROOT), "PATH": "/usr/bin:/bin:/usr/local/bin"})
            js = json.loads((d / "js.json").read_text())
        self.assertEqual(js, json.loads(json.dumps(py)))
        self.assertEqual(py["locations"], ["GB", "EU", "AU", "ME"])
        self.assertTrue({"GB", "DE", "FI", "AU", "AE", "SA"} <= set(py["countries"]))


if __name__ == "__main__":
    unittest.main()
