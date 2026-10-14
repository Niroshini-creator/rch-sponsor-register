"""The browser matcher (candidates/match.js) must give the same scores and labels as candidateboard.match on the real feed."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from candidateboard import match

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "jobs.json"
PROFILE = ROOT / "candidates" / "profiles" / "sample-candidate.json"
RUNNER = """
const fs = require('fs'); const [dir] = process.argv.slice(1); const R = process.env.ROOT;
const I = require(R + '/candidates/intake.js').init(JSON.parse(fs.readFileSync(R + '/candidateboard/roles.json', 'utf8')));
const M = require(R + '/candidates/match.js');
const jobs = JSON.parse(fs.readFileSync(dir + '/jobs.json', 'utf8'));
const out = JSON.parse(fs.readFileSync(dir + '/profiles.json', 'utf8')).map(p => { const m = M.Matcher(p); return jobs.map(j => m.evaluate(j)); });
fs.writeFileSync(dir + '/js.json', JSON.stringify(out));
"""


def variants():
    base = json.loads(PROFILE.read_text())
    a = copy.deepcopy(base)
    b = copy.deepcopy(base); b["driving_licence"] = False; b["clearance"] = {"held": "sc"}; b["experience_years"] = 9
    c = copy.deepcopy(base); c["driving_licence"] = True; c["visa"] = {"type": "citizen", "sponsorship": "not_needed"}
    d = copy.deepcopy(base); d["visa"]["new_entrant"] = False; d["experience_years"] = 2
    e = copy.deepcopy(base); e["english_only"] = False
    return [a, b, c, d, e]


@unittest.skipUnless(shutil.which("node") and FEED.exists() and PROFILE.exists(), "needs node, the shared feed and the sample profile")
class MatchParityTests(unittest.TestCase):
    def test_same_scores_and_labels_on_the_real_feed(self):
        jobs = json.loads(FEED.read_text())["jobs"]          # every country: the language rule only applies outside the English-speaking ones
        profiles = variants()
        py = [[match.Matcher(p).evaluate(j) for j in jobs] for p in profiles]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "jobs.json").write_text(json.dumps(jobs))
            (d / "profiles.json").write_text(json.dumps(profiles))
            subprocess.run(["node", "-e", RUNNER, str(d)], check=True, env={"ROOT": str(ROOT), "PATH": "/usr/bin:/bin:/usr/local/bin"})
            js = json.loads((d / "js.json").read_text())
        scored = 0
        for pi, (a, b) in enumerate(zip(py, js)):
            for job, x, y in zip(jobs, a, b):
                self.assertEqual(json.loads(json.dumps(x)), y, f"profile {pi}: {job['title']} @ {job['company']}")
                scored += x is not None
        self.assertGreater(scored, 100)       # the comparison covered real matches, not just rejections
        language = [(pi, j["title"]) for pi, rows in enumerate(py) for j, ev in zip(jobs, rows) if ev and "language" in ev["hidden_by_default"]]
        self.assertTrue(any(pi != 4 for pi, _ in language) and not any(pi == 4 for pi, _ in language))   # the rule fires, and not when switched off


if __name__ == "__main__":
    unittest.main()
