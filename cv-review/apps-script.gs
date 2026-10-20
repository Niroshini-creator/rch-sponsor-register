/**
 * Resume Crafting Hub - CV enrolment intake (payment is collected afterwards by email).
 * Saves each CV to Google Drive, logs a row in the bound Google Sheet (Status "Enrolled - awaiting payment"),
 * emails HR the details with the CV attached, and sends the candidate an acknowledgement.
 * Work starts only after payment: change Status to PAID in the sheet once the money has arrived.
 * A reminder email is sent once, REMINDER_AFTER_HOURS after enrolling, while the row still says
 * "Enrolled - awaiting payment" (run setupReminderTrigger once to switch this on).
 * Setup steps are in cv-review/README.md.
 */
var HR_EMAIL = "hr@resumecraftinghub.com";
var FOLDER_NAME = "RCH CV Submissions";
var EXPRESS_URL = "https://apply.resumecraftinghub.com/express/";
var WHATSAPP_TEXT = "+91 63692 25896";
var STATUS_WAITING = "Enrolled - awaiting payment";
var REMINDER_AFTER_HOURS = 24;
var USE_ALIAS = false; // true: send as hr@resumecraftinghub.com (add it first in Gmail > Settings > Accounts > "Send mail as"; needs a wider Gmail permission)
var HEADERS = ["Time", "Name", "Email", "Mobile", "Country", "LinkedIn", "Package", "CV link", "Status", "Reminder sent"];
var COL = { TIME: 1, NAME: 2, EMAIL: 3, PLAN: 7, STATUS: 9, REMINDER: 10 };

function doPost(e) {
  try {
    var d = JSON.parse(e.postData.contents);
    if (d.honey) return out({ success: true });
    var bytes = Utilities.base64Decode(d.fileData);
    var blob = Utilities.newBlob(bytes, d.fileType || "application/octet-stream", d.fileName);

    var stamp = Utilities.formatDate(new Date(), "Europe/London", "yyyy-MM-dd_HHmm");
    var safeName = String(d.name || "candidate").replace(/[^\w\- ]/g, "").trim();
    blob.setName(stamp + "_" + safeName + "_" + d.fileName);

    var file = getFolder().createFile(blob);

    var sh = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    if (sh.getLastRow() === 0) sh.appendRow(HEADERS);
    sh.appendRow([new Date(), d.name, d.email, d.phone, d.country, d.linkedin, d.plan, file.getUrl(), STATUS_WAITING, ""]);

    MailApp.sendEmail({
      to: HR_EMAIL,
      replyTo: d.email,
      subject: "NEW ENROLMENT (awaiting payment - do not start work) - " + d.name + " (" + d.plan + ")",
      htmlBody: "<p><b>Name:</b> " + esc(d.name) + "<br><b>Email:</b> " + esc(d.email) +
        "<br><b>Mobile:</b> " + esc(d.phone) + "<br><b>Country:</b> " + esc(d.country) +
        "<br><b>LinkedIn:</b> " + esc(d.linkedin) + "<br><b>Package:</b> " + esc(d.plan) +
        '</p><p><a href="' + file.getUrl() + '">Open CV in Drive</a></p>' +
        "<p><b>Next:</b> email the payment details. Start the update only after payment is received, then deliver within 24-48 hours.</p>",
      attachments: [file.getBlob()]
    });

    sendMail_(d.email, "We received your CV - Resume Crafting Hub",
      "<p>Hi " + esc(d.name) + ",</p><p>Thank you for enrolling for <b>" + esc(d.plan) + "</b>. " +
      "Message us on WhatsApp (" + WHATSAPP_TEXT + ") and we will send you the payment details (UPI if you are paying from India, bank transfer if you are elsewhere). " +
      "Our expert starts work once your payment is received, and you will get your updated CV within 24-48 hours after that.</p>" +
      '<p>See all our options and add-ons: <a href="' + EXPRESS_URL + '">' + EXPRESS_URL + "</a></p>" +
      "<p>Resume Crafting Hub<br>" + HR_EMAIL + "</p>");
    return out({ success: true });
  } catch (err) {
    return out({ success: false, message: String(err) });
  }
}

/** Hourly: remind people who enrolled but have not paid. Sends once per row. */
function sendReminders() {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  var last = sh.getLastRow();
  if (last < 2) return;
  if (!sh.getRange(1, COL.REMINDER).getValue()) sh.getRange(1, COL.REMINDER).setValue(HEADERS[COL.REMINDER - 1]);
  var rows = sh.getRange(2, 1, last - 1, COL.REMINDER).getValues();
  var now = new Date();
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    if (!isDueForReminder_(r[COL.STATUS - 1], r[COL.TIME - 1], r[COL.REMINDER - 1], r[COL.EMAIL - 1], now, REMINDER_AFTER_HOURS)) continue;
    sendMail_(r[COL.EMAIL - 1], "Your CV order is waiting - Resume Crafting Hub",
      "<p>Hi " + esc(r[COL.NAME - 1]) + ",</p><p>You enrolled for <b>" + esc(r[COL.PLAN - 1]) + "</b> and we have your CV. " +
      "To start, message us on WhatsApp (" + WHATSAPP_TEXT + ") and we will send the payment details. " +
      "Our expert starts as soon as payment is received.</p>" +
      '<p>Want a different option or an add-on? <a href="' + EXPRESS_URL + '">' + EXPRESS_URL + "</a></p>" +
      "<p>If you have already paid or no longer need this, just reply and we will stop reminders.</p>" +
      "<p>Resume Crafting Hub<br>" + HR_EMAIL + "</p>");
    sh.getRange(i + 2, COL.REMINDER).setValue(now);
  }
}

/** Pure check, so it can be tested: one reminder, only while unpaid, only after the delay, only with a valid email. */
function isDueForReminder_(status, enrolledAt, reminderSent, email, now, hours) {
  if (status !== STATUS_WAITING || reminderSent) return false;
  if (!/^\S+@\S+\.\S+$/.test(String(email || ""))) return false;
  var t = new Date(enrolledAt).getTime();
  return !isNaN(t) && now.getTime() - t >= hours * 3600 * 1000;
}

/** Run once from the editor to switch on the hourly reminder check. */
function setupReminderTrigger() {
  var exists = ScriptApp.getProjectTriggers().some(function (t) { return t.getHandlerFunction() === "sendReminders"; });
  if (!exists) ScriptApp.newTrigger("sendReminders").timeBased().everyHours(1).create();
}

function sendMail_(to, subject, html) {
  if (USE_ALIAS) {
    GmailApp.sendEmail(to, subject, "", { htmlBody: html, from: HR_EMAIL, replyTo: HR_EMAIL, name: "Resume Crafting Hub" });
  } else {
    MailApp.sendEmail({ to: to, replyTo: HR_EMAIL, name: "Resume Crafting Hub", subject: subject, htmlBody: html });
  }
}

function getFolder() {
  var it = DriveApp.getFoldersByName(FOLDER_NAME);
  return it.hasNext() ? it.next() : DriveApp.createFolder(FOLDER_NAME);
}
function esc(s) { return String(s || "").replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
