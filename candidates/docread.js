/* Read the text of an uploaded CV or list of suitable positions, in the browser (nothing is uploaded).
 * PDF: pdf.js, vendored under /matcher. Word (.docx): unzipped here with the browser's DecompressionStream, list items marked
 * with a bullet (Word keeps the bullet outside the text). Text and Markdown are read as they are. The old binary .doc is not supported. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.DocRead = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const MIN_CHARS = 30;     // less than this from a PDF means it is only pictures

  // ------------------------------------------------------------------ PDF
  let pdfLib = null;
  function loadPdfJs() {
    if (typeof window === "undefined") return Promise.reject(new Error("The PDF reader needs a browser"));
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

  // ------------------------------------------------------------------ Word (.docx = a zip holding word/document.xml)
  const u16 = (b, o) => b[o] | (b[o + 1] << 8);
  const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;

  /** The bytes of one file inside a zip, or null. Reads the central directory, then inflates the entry. */
  async function zipEntry(bytes, wanted) {
    let eocd = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) if (u32(bytes, i) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error("This does not look like a Word (.docx) file");
    let pos = u32(bytes, eocd + 16);
    for (let n = u16(bytes, eocd + 10); n > 0 && u32(bytes, pos) === 0x02014b50; n--) {
      const method = u16(bytes, pos + 10), size = u32(bytes, pos + 20), nameLen = u16(bytes, pos + 28), extra = u16(bytes, pos + 30), comment = u16(bytes, pos + 32), local = u32(bytes, pos + 42);
      const name = new TextDecoder().decode(bytes.subarray(pos + 46, pos + 46 + nameLen));
      if (name === wanted) {
        const start = local + 30 + u16(bytes, local + 26) + u16(bytes, local + 28), data = bytes.subarray(start, start + size);
        if (method === 0) return data;
        if (method !== 8) throw new Error("Unsupported compression in this Word file");
        const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
        return new Uint8Array(await new Response(stream).arrayBuffer());
      }
      pos += 46 + nameLen + extra + comment;
    }
    return null;
  }

  const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'" };
  /** word/document.xml -> plain text: one line per paragraph, list items prefixed with a bullet. */
  function docxXmlToText(xml) {
    const lines = [];
    for (const para of xml.split(/<\/w:p>/)) {
      const text = para.replace(/<w:tab\b[^>]*\/>/g, " ").replace(/<w:br\b[^>]*\/>/g, "\n").replace(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/g, "$1\u0001")
        .replace(/<[^>]+>/g, "").replace(/\u0001/g, "").replace(/&(?:amp|lt|gt|quot|apos);/g, m => ENTITIES[m]).replace(/&#(\d+);/g, (_, d) => String.fromCharCode(Number(d)));
      const clean = text.split("\n").map(l => l.trim()).filter(Boolean);
      if (!clean.length) continue;
      const listed = /<w:numPr>/.test(para);
      clean.forEach((l, i) => lines.push(listed && i === 0 ? `• ${l}` : l));
    }
    return lines.join("\n");
  }
  async function docxText(bytes) {
    const entry = await zipEntry(bytes, "word/document.xml");
    if (!entry) throw new Error("This does not look like a Word (.docx) file");
    return docxXmlToText(new TextDecoder().decode(entry));
  }

  // ------------------------------------------------------------------ any file
  /** Text of a File: PDF, .docx, .txt or .md. Throws a plain-English error for anything unreadable. */
  async function fileText(file) {
    const name = file.name || "file", bytes = new Uint8Array(await file.arrayBuffer());
    let text;
    if (/\.pdf$/i.test(name)) text = await pdfText(bytes);
    else if (/\.docx$/i.test(name)) text = await docxText(bytes);
    else if (/\.doc$/i.test(name)) throw new Error(`${name}: old Word (.doc) files cannot be read. Save it as .docx or PDF and attach that.`);
    else text = new TextDecoder().decode(bytes);
    if (text.trim().length < MIN_CHARS) throw new Error(`${name}: no readable text (a scanned PDF is only pictures). Attach a text-based PDF, a Word file or a text file.`);
    return text;
  }
  return { fileText, docxText, docxXmlToText, zipEntry };
});
