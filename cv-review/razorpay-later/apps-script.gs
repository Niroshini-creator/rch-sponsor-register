/**
 * Resume Crafting Hub - paid CV intake (Razorpay).
 *
 * 1. createOrder: creates a Razorpay order (price is fixed HERE, not in the browser)
 *    and logs the lead as "Awaiting payment" (no CV yet).
 * 2. submit: verifies the Razorpay payment signature; only then saves the CV to Drive,
 *    marks the row "PAID", and emails HR the CV.
 *
 * Secrets live in Project Settings > Script properties (never in the repo):
 *   RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
 */
var HR_EMAIL = "hr@resumecraftinghub.com";
var FOLDER_NAME = "RCH CV Submissions";
var PLANS = {
  "CV Review & Update - GBP 85": 8500,        // pence
  "Full Placement Support - GBP 380": 38000
};
var CURRENCY = "GBP";
var HEADERS = ["Time", "Name", "Email", "Mobile", "Country", "LinkedIn", "Package", "Status", "Order ID", "Payment ID", "CV link"];
var COL = { STATUS: 8, ORDER: 9, PAYMENT: 10, CV: 11 };

function doPost(e) {
  try {
    var d = JSON.parse(e.postData.contents);
    if (d.honey) return out({ success: false, message: "Rejected" });
    if (d.action === "createOrder") return out(createOrder(d));
    if (d.action === "submit") return out(submitPaid(d));
    return out({ success: false, message: "Unknown action" });
  } catch (err) {
    return out({ success: false, message: String(err) });
  }
}

function createOrder(d) {
  var amount = PLANS[d.plan];
  if (!amount) throw new Error("Unknown package");
  if (!/^\S+@\S+\.\S+$/.test(d.email || "")) throw new Error("Invalid email");
  var p = props();
  var res = UrlFetchApp.fetch("https://api.razorpay.com/v1/orders", {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Basic " + Utilities.base64Encode(p.RAZORPAY_KEY_ID + ":" + p.RAZORPAY_KEY_SECRET) },
    payload: JSON.stringify({ amount: amount, currency: CURRENCY, notes: { name: d.name, email: d.email, plan: d.plan } }),
    muteHttpExceptions: true
  });
  var o = JSON.parse(res.getContentText());
  if (!o.id) throw new Error((o.error && o.error.description) || "Could not create order");
  sheet().appendRow([new Date(), d.name, d.email, d.phone, d.country, d.linkedin, d.plan, "Awaiting payment", o.id, "", ""]);
  return { success: true, orderId: o.id, keyId: p.RAZORPAY_KEY_ID, amount: amount, currency: CURRENCY };
}

function submitPaid(d) {
  var secret = props().RAZORPAY_KEY_SECRET;
  var expected = hex(Utilities.computeHmacSha256Signature(d.orderId + "|" + d.paymentId, secret));
  if (expected !== d.signature) throw new Error("Payment could not be verified");

  var sh = sheet();
  var cell = sh.getRange(1, COL.ORDER, sh.getLastRow(), 1).createTextFinder(d.orderId).matchEntireCell(true).findNext();
  if (!cell) throw new Error("Order not found");
  var row = cell.getRow();
  var r = sh.getRange(row, 1, 1, HEADERS.length).getValues()[0];
  if (r[COL.STATUS - 1] === "PAID") throw new Error("This payment was already used");

  var bytes = Utilities.base64Decode(d.fileData);
  var stamp = Utilities.formatDate(new Date(), "Europe/London", "yyyy-MM-dd_HHmm");
  var safe = String(r[1]).replace(/[^\w\- ]/g, "").trim();
  var blob = Utilities.newBlob(bytes, d.fileType || "application/octet-stream", stamp + "_" + safe + "_" + d.fileName);
  var file = getFolder().createFile(blob);

  sh.getRange(row, COL.STATUS, 1, 4).setValues([["PAID", d.orderId, d.paymentId, file.getUrl()]]);

  MailApp.sendEmail({
    to: HR_EMAIL,
    replyTo: r[2],
    subject: "PAID - CV update: " + r[1] + " (" + r[6] + ")",
    htmlBody: "<p><b>Payment confirmed</b> (Razorpay " + esc(d.paymentId) + ")</p><p><b>Name:</b> " + esc(r[1]) +
      "<br><b>Email:</b> " + esc(r[2]) + "<br><b>Mobile:</b> " + esc(r[3]) + "<br><b>Country:</b> " + esc(r[4]) +
      "<br><b>LinkedIn:</b> " + esc(r[5]) + "<br><b>Package:</b> " + esc(r[6]) +
      '</p><p><a href="' + file.getUrl() + '">Open CV in Drive</a></p><p>Deadline: send the updated CV within 24-48 hours.</p>',
    attachments: [file.getBlob()]
  });
  return { success: true };
}

function props() {
  var p = PropertiesService.getScriptProperties().getProperties();
  if (!p.RAZORPAY_KEY_ID || !p.RAZORPAY_KEY_SECRET) throw new Error("Razorpay keys are not set");
  return p;
}
function sheet() {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  if (sh.getLastRow() === 0) sh.appendRow(HEADERS);
  return sh;
}
function getFolder() {
  var it = DriveApp.getFoldersByName(FOLDER_NAME);
  return it.hasNext() ? it.next() : DriveApp.createFolder(FOLDER_NAME);
}
function hex(bytes) { return bytes.map(function (b) { return ("0" + (b < 0 ? b + 256 : b).toString(16)).slice(-2); }).join(""); }
function esc(s) { return String(s || "").replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
