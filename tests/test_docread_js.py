"""Attaching a document of suitable positions: Word reader, list parser parity (Python vs browser) and addPositions."""
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from candidateboard import cv

ROOT = Path(__file__).resolve().parent.parent
ENV = {"ROOT": str(ROOT), "PATH": "/usr/bin:/bin:/usr/local/bin"}
LAYOUTS = {
    "bullets": "Business Analyst CV\n• Business Analyst\n• Requirements Analyst (remote)\nSAP CV\n● SAP Security Consultant / GRC Analyst\n",
    "numbered": "1. Data Analyst\n2) Project Coordinator\n",
    "plain": "Suitable roles for you:\nData Analyst\nBusiness Analyst\nService Desk Analyst\nEmail me at jo@example.com\n",
    "commas": "Data Analyst, Business Analyst, Service Desk Analyst\n",
    "mixed": "Marketing Executive / Coordinator\n- Finance Officer\n",
}


def make_docx(paragraphs):
    """paragraphs: (text, listed) pairs -> bytes of a minimal real .docx."""
    body = "".join(f"<w:p>{'<w:pPr><w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr></w:pPr>' if listed else ''}<w:r><w:t>{t}</w:t></w:r></w:p>" for t, listed in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


RUNNER = """
const fs = require('fs'); const R = process.env.ROOT; const [dir] = process.argv.slice(1);
const D = require(R + '/candidates/docread.js');
const I = require(R + '/candidates/intake.js').init(JSON.parse(fs.readFileSync(R + '/candidateboard/roles.json', 'utf8')));
(async () => {
  const text = await D.docxText(new Uint8Array(fs.readFileSync(dir + '/a.docx')));
  const layouts = JSON.parse(fs.readFileSync(dir + '/layouts.json', 'utf8'));
  const parsed = Object.fromEntries(Object.entries(layouts).map(([k, v]) => [k, I.parseRoleList(v)]));
  const p = { roles: [{title: 'Business Analyst', family: 'business_analyst', tier: 1, track: 'BA CV', source: 'recruiter list'}], tracks: [{name: 'SAP CV'}, {name: 'BA CV'}] };
  const added = I.addPositions(p, text);
  const again = I.addPositions(p, text);
  fs.writeFileSync(dir + '/out.json', JSON.stringify({ text, parsed, added, again: again.length, roles: p.roles.map(r => r.title) }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node is needed to run the browser code")
class AttachDocumentTests(unittest.TestCase):
    def test_docx_reader_parser_parity_and_add_positions(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.docx").write_bytes(make_docx([("Suitable roles", False), ("Business Analyst", True), ("Data Analyst", True), ("Cloud Security Architect &amp; GRC", True)]))
            (d / "layouts.json").write_text(json.dumps(LAYOUTS))
            subprocess.run(["node", "-e", RUNNER, str(d)], check=True, env=ENV)
            out = json.loads((d / "out.json").read_text())
        self.assertEqual(out["text"], "Suitable roles\n• Business Analyst\n• Data Analyst\n• Cloud Security Architect & GRC")
        for name, text in LAYOUTS.items():
            self.assertEqual(out["parsed"][name], cv.parse_role_list(text), name)
        self.assertEqual([r["title"] for r in cv.parse_role_list(LAYOUTS["numbered"])], ["Data Analyst", "Project Coordinator"])
        self.assertEqual([r["title"] for r in cv.parse_role_list(LAYOUTS["plain"])], ["Data Analyst", "Business Analyst", "Service Desk Analyst"])
        self.assertEqual([r["title"] for r in cv.parse_role_list(LAYOUTS["commas"])], ["Data Analyst", "Business Analyst", "Service Desk Analyst"])
        self.assertEqual([r["title"] for r in out["added"]], ["Data Analyst", "Cloud Security Architect & GRC"])   # the one already held is skipped
        self.assertTrue(all(r["source"] == "attached document" for r in out["added"]))
        self.assertEqual(out["again"], 0)


if __name__ == "__main__":
    unittest.main()
