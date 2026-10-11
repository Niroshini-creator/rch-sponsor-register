"""Does the advertised pay meet the minimum salary for a work visa / permit?

The site cannot know each job's occupation code, so it checks the floors every sponsored worker must clear:

UK Skilled Worker (from 22 July 2025)
  * £41,700 a year general threshold (the occupation's going rate can be higher).
  * £33,400 a year for new entrants (under 26, recent UK graduates, Graduate visa switchers), PhD-level
    jobs and Immigration Salary List roles.
  * £25,000 a year for health and education jobs on national pay scales (NHS clinical roles, school teachers).
Ireland employment permits (from 1 March 2026)
  * €36,605 a year General Employment Permit, €40,904 Critical Skills (with a relevant degree).
  * €32,691 for healthcare assistants and home carers.

Update the figures below when the Home Office or the Department of Enterprise changes them.
"""

from __future__ import annotations

import re

from .models import Job

UK_GENERAL = 41_700
UK_REDUCED = 33_400      # new entrant / PhD / Immigration Salary List floor
UK_PAY_SCALE = 25_000    # health & education occupations on national pay scales
IE_GENERAL = 36_605
IE_CARE = 32_691

HOURS_PER_YEAR = 37.5 * 52

_CURRENCY = {"GB": "£", "IE": "€"}
_OTHER_CURRENCY_RE = {"GB": re.compile(r"[$€]|\b(eur|usd)\b", re.I), "IE": re.compile(r"[$£]|\b(gbp|usd)\b", re.I)}
_NUMBER_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", re.I)
_HOURLY_RE = re.compile(r"\b(per|an|a|each)\s+hour\b|\bhourly\b|\bp/?h\b|/\s*h(ou)?r\b", re.I)
_MONTHLY_RE = re.compile(r"\b(per|a|each)\s+month\b|\bmonthly\b|\bpcm\b|/\s*month\b", re.I)
_WEEKLY_RE = re.compile(r"\b(per|a|each)\s+week\b|\bweekly\b|/\s*week\b", re.I)
_DAILY_RE = re.compile(r"\b(per|a|each)\s+day\b|\bdaily\b|/\s*day\b|\bday rate\b", re.I)
_ANNUAL_RE = re.compile(r"\b(per|a|each)\s+(annum|year)\b|\bannual(ly)?\b|\bp\.?a\.?\b|\byearly\b", re.I)

# Health and education occupations paid on national pay scales (Agenda for Change, medical and teacher pay):
# their floor is £25,000 plus the pay-scale rate. Support, admin and estates staff in the NHS or schools are not.
_HEALTH_TITLE_RE = re.compile(
    r"\b(nurse|nursing sister|charge nurse|midwi(fe|ves|fery)|health visitor|paramedic|doctor|physician|surgeon|"
    r"consultant|registrar|\bgp\b|general practitioner|dentist|dental (officer|surgeon)|pharmacist|radiographer|"
    r"sonographer|physiotherapist|physio\b|occupational therapist|speech (and|&) language therapist|dietitian|"
    r"podiatrist|orthoptist|optometrist|audiologist|biomedical scientist|clinical scientist|(clinical|counselling) "
    r"psychologist|psychotherapist|operating department practitioner)", re.I)
_TEACHER_TITLE_RE = re.compile(r"\b(teacher|head of (department|year|faculty)|senco|headteacher|head teacher)\b", re.I)
_TRAINEE_RE = re.compile(r"\b(trainee|student|assistant|support worker|apprentice|hca|dental nurse|nursery nurse|"
                         r"nursing associate)\b", re.I)
_IE_CARE_RE = re.compile(r"\b(healthcare assistant|health care assistant|care assistant|home carer|care worker)\b", re.I)


def annual_range(salary: str, country: str) -> tuple[float, float] | None:
    """The advertised pay as a yearly (low, high) in the country's currency, or None when it can't be read.

    Day rates and bare amounts that could be weekly or monthly are left unread rather than guessed.
    """
    if not salary or (country in _OTHER_CURRENCY_RE and _OTHER_CURRENCY_RE[country].search(salary)):
        return None
    numbers = [float(n.replace(",", "")) * (1000 if k else 1) for n, k in _NUMBER_RE.findall(salary)
               if n.replace(",", "").replace(".", "").isdigit()]
    if not numbers:
        return None
    if _DAILY_RE.search(salary):
        return None
    if _HOURLY_RE.search(salary):
        rates = [n for n in numbers if 5 <= n < 200]
        return (min(rates) * HOURS_PER_YEAR, max(rates) * HOURS_PER_YEAR) if rates else None
    if _MONTHLY_RE.search(salary):
        months = [n for n in numbers if 500 <= n < 50_000]
        return (min(months) * 12, max(months) * 12) if months else None
    if _WEEKLY_RE.search(salary):
        weeks = [n for n in numbers if 100 <= n < 10_000]
        return (min(weeks) * 52, max(weeks) * 52) if weeks else None
    years = [n for n in numbers if n >= 10_000 and n < 2_000_000]
    if years:
        return min(years), max(years)
    if _ANNUAL_RE.search(salary):
        # A stated annual figure under 10,000: part-time pay ("£3,752 Annually (Actual)").
        small = [n for n in numbers if n >= 1000]
        return (min(small), max(small)) if small else None
    # A bare amount under 100 is an hourly rate (NHS bank shifts, Reed's "13"); 100-9,999 is ambiguous.
    rates = [n for n in numbers if 5 <= n < 100]
    if rates and len(rates) == len(numbers):
        return min(rates) * HOURS_PER_YEAR, max(rates) * HOURS_PER_YEAR
    return None


def thresholds(job: Job) -> tuple[int, int] | None:
    """(full minimum, lowest minimum any applicant could use) for the job's country, or None if not checked."""
    if job.country == "GB":
        clinical = _HEALTH_TITLE_RE.search(job.title) and (
            job.domain == "Healthcare & Clinical" or job.sector == "NHS & Healthcare")
        if (clinical or _TEACHER_TITLE_RE.search(job.title)) and not _TRAINEE_RE.search(job.title):
            return UK_PAY_SCALE, UK_PAY_SCALE
        return UK_GENERAL, UK_REDUCED
    if job.country == "IE":
        if _IE_CARE_RE.search(job.title):
            return IE_CARE, IE_CARE
        return IE_GENERAL, IE_GENERAL
    return None


def salary_check(job: Job) -> tuple[str, int, int]:
    """("meets" | "partial" | "reduced" | "below" | "", annual high, threshold).

    meets    the whole pay range is at or above the full minimum
    partial  only the top of the range reaches it
    reduced  below the full minimum but at or above the new-entrant / PhD rate (UK)
    below    under every minimum: the job cannot be sponsored at this pay
    ""       not checked (pay not stated or unreadable, or a country without a check)
    """
    limits = thresholds(job)
    pay = annual_range(job.salary, job.country) if limits else None
    if not limits or not pay:
        return "", 0, limits[0] if limits else 0
    full, lowest = limits
    low, high = pay
    if low >= full:
        status = "meets"
    elif high >= full:
        status = "partial"
    elif high >= lowest:
        status = "reduced"
    else:
        status = "below"
    return status, round(high), full


def currency(country: str) -> str:
    return _CURRENCY.get(country, "")
