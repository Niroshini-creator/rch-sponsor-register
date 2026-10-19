/**
 * Resume Crafting Hub - CV enrolment intake (payment is collected afterwards by email).
 * Saves each CV to Google Drive, logs a row in the bound Google Sheet (Status "Enrolled - awaiting payment"),
 * emails HR the details with the CV attached, and sends the candidate an acknowledgement.
 * Work starts only after payment: change Status to PAID in the sheet once the money has arrived.
 * Setup steps are in cv-review/README.md.
 */
var HR_EMAIL = "hr@resumecraftinghub.com";
var FOLDER_NAME = "RCH CV Submissions";
var HEADERS = ["Time", "Name", "Email", "Mobile", "Country", "LinkedIn", "Package", "CV link", "Status"];

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
    sh.appendRow([new Date(), d.name, d.email, d.phone, d.country, d.linkedin, d.plan, file.getUrl(), "Enrolled - awaiting payment"]);

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

    MailApp.sendEmail({
      to: d.email,
      replyTo: HR_EMAIL,
      name: "Resume Crafting Hub",
      subject: "We received your CV - Resume Crafting Hub",
      htmlBody: "<p>Hi " + esc(d.name) + ",</p><p>Thank you for enrolling for <b>" + esc(d.plan) + "</b>. " +
        "Message us on WhatsApp (+91 63692 25896) and we will send you the payment details (UPI if you are paying from India, bank transfer if you are elsewhere). " +
        "Our expert starts work once your payment is received, " +
        "and you will get your updated CV within 24-48 hours after that.</p><p>Resume Crafting Hub<br>" + HR_EMAIL + "</p>"
    });
    return out({ success: true });
  } catch (err) {
    return out({ success: false, message: String(err) });
  }
}

function getFolder() {
  var it = DriveApp.getFoldersByName(FOLDER_NAME);
  return it.hasNext() ? it.next() : DriveApp.createFolder(FOLDER_NAME);
}
function esc(s) { return String(s || "").replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
