# Free CV & LinkedIn Review funnel

Page: `cv-review/index.html` (live at `/cv-review/` on GitHub Pages).

## Flow (enrolment first, payment by email)
Upload CV -> free scan (sample findings) -> choose £85 CV+LinkedIn update or £380 Full Placement Support -> name/email/mobile/CV submitted -> CV saved to Google Drive, row added to the sheet as **Enrolled - awaiting payment**, HR emailed, candidate gets an acknowledgement -> you email the payment details -> **work starts only after payment is received** -> updated CV emailed within 24-48 h.

When money arrives, change the sheet row's Status to `PAID`.

## Google Apps Script (bound to the sheet)
1. Open the sheet > Extensions > Apps Script, paste `apps-script.gs`, save.
2. Run `getFolder` once and approve permissions (Drive, Sheets, Gmail).
3. Deploy > Manage deployments > pencil > New version > Deploy (access: Anyone). The URL stays the same and is set as `SCRIPT_URL` in `index.html`.

## Automatic emails
- **Instant thank-you** when someone enrols, with a link to the express options page.
- **One reminder after 24 hours** (`REMINDER_AFTER_HOURS`) if the sheet row still says `Enrolled - awaiting payment`. Change Status to `PAID` (or anything else) once they pay or opt out, and no reminder is sent. The row's "Reminder sent" column records the send.
- Switch the reminders on once: in Apps Script pick `setupReminderTrigger` in the function dropdown, click Run, and allow the permissions (it also needs permission to manage triggers). It then checks hourly.
- Emails go out from your Google account with reply-to `hr@resumecraftinghub.com`. To show `hr@resumecraftinghub.com` as the sender, add it in Gmail (Settings > Accounts > Send mail as, SMTP `smtp.hostinger.com`, port 465) and set `USE_ALIAS = true` in the script. This needs a wider Gmail permission.
- Free Gmail accounts can send about 100 script emails a day.

## Later: automatic payment
The Razorpay version (pay on the page, CV accepted only after verified payment) is kept in `cv-review/razorpay-later/` (`index.html.txt`, `apps-script.gs`). It needs Razorpay approval, API keys in Script properties, and a new version deploy.

## Sharing
Link: `https://apply.resumecraftinghub.com/cv-review/`
See `share-messages.md` for copy-paste posts.
