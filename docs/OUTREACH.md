# Outreach automation (employers + candidates, UK / Ireland / Europe)

`python -m outreach` runs multi-step outreach campaigns for a placement-support business:

* **Employers** (B2B): cold email sequences and cold-call sheets, pitching candidates who already have the right to
  work (UK Graduate visa / PSW, Dependant visa, Irish Stamp 1G / Stamp 4).
* **Candidates** (PSW, dependants, Stamp 1G holders in the UK, Dublin and the rest of Ireland, and Europe): email,
  SMS and WhatsApp sequences, **only to people who opted in** (see *Getting candidate consent*).

Every message goes through a compliance gate first, every action is logged, and sequences stop on their own
when someone replies, opts out, bounces or asks not to be called. Like `jobfeed`, it is standard-library Python
3.10+ with no dependencies.

> This is a practical summary, not legal advice. Have the rules below checked once by a UK / Irish adviser
> before you go live, especially if you charge candidates anything.

## How it works

```
 contacts/*.csv ──► compliance gate ──► campaign step due? ──► render template + opt-out footer
 (employers,        (consent, TPS,      (day offsets,           │
  candidates)        suppression,        48h gap, hours,        ├─ email     → SMTP
                     B2B rules)          daily caps)            ├─ sms/whatsapp → Twilio
                                                                └─ call      → today's call sheet (a person dials)
                       ▲                                                          │
 replies / opt-outs ───┴──── scan-inbox (IMAP), log-calls, mark  ◄─── ledger.jsonl (audit log)
```

## Quick start

```bash
# 1. your details (PECR: every message must identify you and give a contact address)
$EDITOR config/outreach.json            # sender.name/company/address/email, booking link

# 2. contacts – outreach_data/ is git-ignored; it holds personal data and must never be committed
mkdir -p outreach_data && cp -r outreach_data.example/contacts outreach_data/
python -m outreach import-employers     # optional: recruitment inboxes from adverts in data/jobs.json

# 3. see who you can reach, and why not
python -m outreach check
python -m outreach plan -v              # today's messages, fully rendered

# 4. dry run (writes outreach_data/outbox.jsonl), then live
python -m outreach send
export OUTREACH_SMTP_HOST=smtp.example.com OUTREACH_SMTP_USER=… OUTREACH_SMTP_PASSWORD=…
python -m outreach send --live
```

### Daily routine (schedule it)

Run it on a machine or a **private** server you control, not in this public repository's GitHub Actions:
the contact list and ledger are personal data.

```cron
# Tue–Thu 09:05 UK time: record replies/opt-outs, then send what's due and write today's call sheet
5 9 * * 2-4  cd /srv/rch-sponsor-register && . ./.env && python -m outreach run --live >> outreach_data/run.log 2>&1
```

Then during the day:

1. Open `outreach_data/calls/<date>.csv`, make the calls using the script column, fill in `outcome`
   (`no_answer`, `voicemail`, `callback`, `interested`, `not_interested`, `do_not_call`, `wrong_number`).
2. `python -m outreach log-calls outreach_data/calls/<date>.csv`
3. Anything that came in another way: `python -m outreach mark interested --phone +4477…`,
   `python -m outreach mark unsubscribed --email …` (also works for people not in your list: they go straight
   on the suppression list).
4. `python -m outreach report` for the funnel per campaign.

## Contacts

CSV files in `outreach_data/contacts/` (any file name). Columns are documented in
[`outreach/contacts.py`](../outreach/contacts.py); examples in [`outreach_data.example/`](../outreach_data.example/).
The important ones:

| Column | Used for |
|---|---|
| `audience` | `employer` or `candidate` – decides which rules apply |
| `country` | `GB`, `IE`, `NL`, … – rules, sending hours (local time) and phone format |
| `visa` | `psw`, `dependant`, `stamp1g`, `stamp4`, `skilled_worker`, `other` – campaign filters and wording |
| `source` | where you got an employer contact (URL of the careers page / advert). Required for B2B cold email |
| `consent_channels`, `consent_date`, `consent_source` | e.g. `email;sms;whatsapp`, `2026-09-20`, `Website registration form`. All three needed |
| `relationship`, `relationship_date` | `enquired` / `client`: soft opt-in for someone who asked about your service |
| `tps_status`, `tps_checked_on` | `clear` / `registered` and the date of your last TPS/CTPS (UK) or NDD (IE) screen |

## Campaigns and templates

Campaigns live in [`config/outreach.json`](../config/outreach.json). Each one picks an audience, an optional
filter on any contact column, and steps run on day offsets from the first message:

```json
"candidate_ie_stamp1g": {
  "audience": "candidate",
  "filter": {"country": ["IE"], "visa": ["stamp1g", "stamp4", "dependant"]},
  "steps": [
    {"day": 0,  "channel": "email", "template": "candidate_ie_intro"},
    {"day": 3,  "channel": "sms",   "template": "candidate_sms"},
    {"day": 10, "channel": "email", "template": "candidate_followup"}
  ]
}
```

Shipped campaigns: `employer_intro` (email → follow-up → call → last email, GB + IE), `candidate_uk_psw_dependant`,
`candidate_ie_stamp1g`, `candidate_europe`. Set `"active": false` to pause one.

Templates are text files in [`templates/outreach/`](../templates/outreach/). Email templates start with
`Subject:`. Placeholders: `${first_name}`, `${name}`, `${company}`, `${role}`, `${city}`, `${visa}` (e.g. "Graduate
visa (PSW)"), `${target_role}`, `${notes}` and every `sender` field as `${sender_…}`. The identity + opt-out footer is
added automatically. `check` lints templates and rejects:

* guarantees of a job, interview, visa or sponsorship, and placement-rate promises (misleading to job seekers);
* **fees charged to candidates for finding them work** (see below);
* unknown placeholders, missing subjects, SMS longer than 3 segments.

Built-in safeguards: one touch per contact per run, at least `min_hours_between_touches` (48h) between any two
touches across all campaigns, per-channel daily caps, 45 s between messages, sending only in the contact's local
business hours (employers Tue–Thu, candidates Mon–Sat), and a failed send is retried on the next run.

## The rules the gate enforces

### Employers (B2B)

* **Email**: allowed without consent to a **business** address (not Gmail/Outlook/etc.) in the UK (PECR reg. 22 does
  not cover corporate subscribers) and Ireland (S.I. 336/2011 reg. 13 allows it to non-natural persons), as long as
  every email identifies you and offers an opt-out, and you record where you found the address. UK GDPR still applies
  to named employees: keep a short *legitimate interests assessment* and honour objections. **Other EU countries**
  are blocked by default: Germany, Austria, Denmark, Italy and others require prior consent even for B2B email. Add
  a country to `b2b_cold_email_countries` only after checking its law.
* **Calls**: screen numbers against the **CTPS** (UK) or the **NDD opt-out register** (IE) at most 28 days before
  calling (`tps_status=clear`, `tps_checked_on`). Irish mobiles need consent. Say who you are on every call.
* **SMS / WhatsApp**: consent only.

### Candidates (individuals)

* **Email / SMS / WhatsApp**: consent for that channel, with date and source, or **soft opt-in** (they enquired about
  or used your service: 24 months in the config for the UK, 12 months for Ireland, where it is the legal limit).
  **Buying, scraping or copying lists of migrants from Facebook / WhatsApp / LinkedIn groups and messaging them is
  unlawful** (PECR reg. 22, S.I. 336/2011 reg. 13, GDPR art. 6/14) and the gate blocks it.
* **Calls**: consent, or a clear **TPS** screen within 28 days (UK). Irish mobiles need consent.
* Contacts whose `visa_expiry` has passed are not contacted.

### Everyone

* Opt-outs (email reply, `STOP` by SMS, a `do_not_call` call outcome, `mark`) go on
  `outreach_data/suppression.csv` and are kept for good, so re-importing a list can't undo them. Whole domains can
  be blocked with a row like `@company.com`.
* No automated / pre-recorded calls (they need explicit prior consent in both countries).
* Keep `outreach_data/` private, back it up, and delete candidates you no longer need.

### Running a placement business

* **No fees from candidates for finding them work.** In the UK, the Employment Agencies Act 1973 s.6 and the
  Conduct of Employment Agencies Regulations 2003 forbid charging work-seekers for work-finding services (narrow
  exceptions, e.g. some entertainment/modelling roles). In Ireland, employment agencies need a licence under the
  Employment Agency Act 1971 and may not charge job seekers fees. Optional paid services (CV writing, training) must
  never be a condition of being put forward for jobs. Charge employers instead.
* Register with the **ICO** (UK data protection fee) and, for Ireland, be ready for the **DPC**; publish a privacy
  notice and link it from your sign-up forms.
* Don't advise on immigration: in the UK that is regulated by the IAA (formerly OISC). Point candidates to GOV.UK /
  irishimmigration.ie or a regulated adviser.

## Getting candidate consent (the lawful way to reach PSW, dependant and Stamp 1G holders)

Grow an opt-in list and the automation does the rest:

1. A **registration form** (website, Google Form, Typeform, Tally) with *separate, unticked* boxes: "Email me job
   updates", "Text / WhatsApp me job updates", "Call me". Store the timestamp and form name → `consent_date`,
   `consent_source`.
2. Bring people to it with: posts and content on LinkedIn, Instagram and TikTok; **LinkedIn / Meta lead-gen ads**
   targeted to the UK and Dublin (their forms include a consent question); free webinars ("Finding a job on a
   Graduate visa", "Stamp 1G to Critical Skills"); university international-student offices and alumni groups;
   community events; and referrals from placed candidates. Posting a link *in* a community group is fine where the
   admins allow it; messaging its members one by one is not.
3. Export the form responses to `outreach_data/contacts/candidates.csv` (same columns) and the sequences pick
   them up on the next run.

## Channels and credentials

All credentials are environment variables (put them in a private `.env`, never in git):

| Channel | Variables | Notes |
|---|---|---|
| Email | `OUTREACH_SMTP_HOST`, `OUTREACH_SMTP_PORT` (587), `OUTREACH_SMTP_USER`, `OUTREACH_SMTP_PASSWORD` | Google Workspace, Microsoft 365, Zoho, Mailgun, Postmark, SES… |
| Replies | `OUTREACH_IMAP_HOST`, `OUTREACH_IMAP_USER`, `OUTREACH_IMAP_PASSWORD`, `OUTREACH_IMAP_FOLDER` | read-only; messages stay unread |
| SMS | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM` | Twilio handles STOP replies; also `mark unsubscribed --phone` |
| WhatsApp | same + `TWILIO_WHATSAPP_FROM` | the first message must be a Meta-approved template: set `content_sid` and `content_variables` on the step |

**Email deliverability** (cold email lives or dies on this):

* Send from a separate domain (e.g. `yourcompany-talent.co.uk`) so your main domain's reputation is protected, with
  **SPF, DKIM and DMARC** set up and a real website on it.
* Warm up: start at 10–20 emails a day and raise `email_per_day` by ~10 a week, up to 50–80 per mailbox.
* Plain text, no attachments, one link at most, personalise the first line (`notes` column).
* Keep bounces under 2 %: verify imported addresses first. `scan-inbox` suppresses bounces automatically.

## Files

```
outreach/contacts.py     CSV loading, validation, phone normalisation, import from data/jobs.json
outreach/compliance.py   the gate: consent, soft opt-in, B2B rules, TPS/CTPS/NDD, suppression
outreach/templates.py    templates, personalisation, opt-out footer, content lint
outreach/engine.py       sequences: who gets which step today
outreach/channels.py     SMTP, Twilio SMS/WhatsApp, dry-run outbox
outreach/calls.py        call sheets and outcome import
outreach/inbox.py        IMAP reply / opt-out / bounce detection
outreach/ledger.py       audit log + suppression list
config/outreach.json     sender, limits, hours, rules, campaigns
templates/outreach/      message and call-script templates
outreach_data/           (git-ignored) contacts, ledger.jsonl, suppression.csv, outbox, call sheets
```
