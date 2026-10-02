"""Rules that label each job: sponsorship evidence, role domain, employer sector, tier and size."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import Job
from .text import normalise_company

# ----------------------------------------------------------------------------- sponsorship
_POSITIVE = [re.compile(p, re.I) for p in (
    r"visa sponsorship (is |will be |may be |can be )?(available|offered|provided|considered|possible)",
    r"sponsorship (is |will be |may be |can be )?(available|offered|provided|considered)",
    r"(able|willing|happy|pleased|can|will) to (offer|provide|consider|support) (visa |skilled worker |a )?sponsorship",
    r"eligible for (visa |skilled worker )?sponsorship",
    r"(we|employer|trust|university|school) (can |will |may )?(offer|provide|sponsor)s? (a )?(skilled worker |work )?visa",
    r"skilled worker (visa|route) sponsorship",
    r"certificate of sponsorship",
    r"require[sd]? .{0,40}sponsorship .{0,80}(welcome|considered|encouraged)",
    r"\bvisa (support|assistance|sponsorship) (provided|available|offered|included)",
    r"\b(eu )?blue card\b",
    r"relocation (and|&) visa (support|assistance)",
    r"work permit (support|assistance|sponsorship)",
    r"\bsponsorship\s*:\s*(yes|available)",
    r"(help|support|assist)\w* (you )?with (the |your )?(visa|work permit|residence permit|immigration)",
    r"(work|residence) permit (will be |can be )?(arranged|provided|sponsored|handled)",
    r"\bh-?1b (sponsorship|transfer)s? (is |are )?(available|offered|provided|considered|supported|welcome)",
    r"(will|can|happy to|able to) sponsor (an? |your )?(h-?1b|visa|work visa|green card)",
    r"\bgreen card sponsorship\b",
)]
_STRONG_NEGATIVE = [re.compile(p, re.I) for p in (
    r"(unable|not able|cannot|can ?not|can't|do not|don't|does not|doesn't|won't|will not|are not able|is not able)"
    r" (to )?(offer|provide|consider|support|accept)?\s*(visa |skilled worker |any |h-?1b |immigration |employment )*sponsor",
    r"\bno (visa |skilled worker )?sponsorship",
    r"sponsorship (is |will )?not (be )?(available|offered|provided|possible|considered)",
    r"not eligible for (visa |skilled worker )?sponsorship",
    r"without (the need for |requiring |requirement for )?(visa |skilled worker |any )?sponsorship",
    r"sponsorship\s*:\s*no\b",
    r"\b(us|u\.s\.) citizenship (is )?required\b|\bmust be an? (us|u\.s\.) citizen\b|security clearance (is )?required",
)]
_WEAK_NEGATIVE = [re.compile(p, re.I) for p in (
    r"must (already )?(have|hold) (the |a |full |existing |an existing )*right to work",
)]


def sponsorship_signal(text: str) -> str:
    """Return "positive", "negative" or "" (no statement) for an advert's text."""
    if any(p.search(text) for p in _STRONG_NEGATIVE):
        return "negative"
    if any(p.search(text) for p in _POSITIVE):
        return "positive"
    if any(p.search(text) for p in _WEAK_NEGATIVE):
        return "negative"
    return ""


# ----------------------------------------------------------------------------- sector (employer type)
SECTORS = ["NHS & Healthcare", "University & Research Institute", "School & College",
           "Public Sector & Government", "Private Sector", "Charity & Non-profit"]

_SECTOR_RULES: list[tuple[str, re.Pattern]] = [
    ("NHS & Healthcare", re.compile(
        r"\bnhs\b|\bhealth ?(board|care|service)s?\b|\bhospitals?\b|foundation trust|\bccg\b|\bicb\b|"
        r"integrated care|\bgp (surgery|practice)\b|medical (centre|practice)|\bklinik|\bclinic\b", re.I)),
    ("University & Research Institute", re.compile(
        r"\buniversit|\bhochschule\b|\bcollege london\b|imperial college|king's college|\binstitute of\b|"
        r"research (institute|council|centre)|\bmax planck|fraunhofer|\bcnrs\b|\bukri\b|\bwellcome sanger\b|"
        r"francis crick|\bcern\b|\bembl\b", re.I)),
    ("School & College", re.compile(
        r"\bschools?\b|\bacadem(y|ies)\b|\bcollege\b|multi.academy trust|\bsixth form\b|"
        r"\bgrammar\b|\bprimary\b|\bsecondary\b|\bnursery\b|\bgymnasium\b|\bschule\b", re.I)),
    ("Public Sector & Government", re.compile(
        r"\bcouncil\b|\bgovernment\b|\bministry\b|\bdepartment for\b|\bhm (revenue|treasury|courts)|"
        r"\bcivil service\b|\bpolice\b|\bfire (and|&) rescue\b|\bhome office\b|\bmet office\b|\bofcom\b|"
        r"\bborough\b|\b(local|combined|transport|port|regulatory) authority\b|\bexecutive agency\b|"
        r"\b(environment|food standards|health security|space) agency\b|\bgemeente\b|\bstadt\b|\bbundes|"
        r"\beuropean (union|commission|parliament|central bank|investment bank|medicines agency)\b|\bparliament\b", re.I)),
    ("Charity & Non-profit", re.compile(
        r"\bcharit|\bfoundation\b|\bnon.?profit\b|\bngo\b|\bhousing association\b|\bred cross\b|\boxfam\b", re.I)),
]


def classify_sector(job: Job) -> str:
    for sector, rx in _SECTOR_RULES:
        if rx.search(job.company):
            return sector
    if job.source == "NHS Jobs":
        return "NHS & Healthcare"
    if job.source == "Teaching Vacancies":
        return "School & College"
    return "Private Sector"


# ----------------------------------------------------------------------------- domain (role function)
DOMAINS = ["Technical & Engineering", "Management & Business", "Science & Research",
           "Healthcare & Clinical", "Teaching & Academic", "Finance & Legal", "Other"]

_DOMAIN_RULES: list[tuple[str, re.Pattern]] = [
    ("Healthcare & Clinical", re.compile(
        r"\bnurs(e|ing)\b|\bdoctor\b|\bphysician\b|\bconsultant (in|psychiatrist|surgeon|physician|anaesth|radiolog)|"
        r"\bregistrar\b|\bmidwi|\bradiograph|\bphysiotherap|\boccupational therap|\bparamedic\b|\bpharmacist\b|"
        r"\bclinical\b|\bsurgeon\b|\bspeciality doctor\b|\bpsychiatr|\bpsycholog|\bdentist|\bgp\b|"
        r"\bsonograph|\bhealth care assistant\b|\bcare assistant\b|\bsenior carer\b|\bsupport worker\b", re.I)),
    ("Teaching & Academic", re.compile(
        r"\bteacher\b|\bteaching\b|\blecturer\b|\bprofessor\b|\bsenco\b|\bhead of (department|year|maths|science|english)|"
        r"\btutor\b|\breader in\b|\bassociate professor\b|\bteaching fellow\b|\bdeputy head\b|\bheadteacher\b", re.I)),
    ("Science & Research", re.compile(
        r"\bscientist\b|\bresearch(er| fellow| associate| assistant)\b|\bpostdoc|\bpost-doctoral|\bchemist\b|"
        r"\bbiolog|\bphysicist\b|\blaboratory\b|\blab\b|\bgenomic|\bbioinformatic|\bepidemiolog|\bstatistician\b|"
        r"\bclinical trial|\bpharmacolog|\bmolecular\b|\bmicrobiolog|\bneuroscien|\bphd\b", re.I)),
    ("Technical & Engineering", re.compile(
        r"\bengineer|\bdeveloper\b|\bsoftware\b|\bprogrammer\b|\bdevops\b|\bdata (analyst|engineer|architect)\b|"
        r"\bmachine learning\b|\b(ai|ml)\b|\bcloud\b|\bsecurity analyst\b|\bcyber\b|\barchitect\b|\bit (support|manager)\b|"
        r"\bnetwork\b|\bsysadmin\b|\bsre\b|\bfull.?stack\b|\bfront.?end\b|\bback.?end\b|\bqa\b|\btester\b|"
        r"\btechnician\b|\bcad\b|\bmechanical\b|\belectrical\b|\bcivil engineer|\bsurveyor\b|\bdesigner\b", re.I)),
    ("Finance & Legal", re.compile(
        r"\baccountant\b|\baccounting\b|\bfinanc|\baudit|\btax\b|\bactuar|\bsolicitor\b|\blawyer\b|\blegal\b|"
        r"\bparalegal\b|\bcompliance\b|\brisk analyst\b|\bquant\b|\btreasury\b|\bpayroll\b", re.I)),
    ("Management & Business", re.compile(
        r"\bmanager\b|\bdirector\b|\bhead of\b|\blead\b|\bchief\b|\bproject manag|\bprogramme manag|\bproduct manag|"
        r"\boperations\b|\bconsultant\b|\bbusiness analyst\b|\bstrateg|\bmarketing\b|\bsales\b|\bhr\b|"
        r"\bhuman resources\b|\bprocurement\b|\bsupply chain\b|\blogistics\b|\badministrat|\bofficer\b", re.I)),
]


def classify_domain(job: Job) -> str:
    for text in (job.title, job.description[:600]):
        for domain, rx in _DOMAIN_RULES:
            if rx.search(text):
                return domain
    return "Other"


# ----------------------------------------------------------------------------- job role (job family)
ROLES = ["Software Developer", "DevOps & Cloud", "Data Science & AI", "Data Analyst", "Business Analyst",
         "IT Support", "Application Support", "Engineering", "Project Manager", "Finance & Accounting",
         "HR & Recruitment", "Digital Marketing", "Logistics & Supply Chain", "Medical Laboratory", "Aviation",
         "Other"]

# Ordered most specific first: "Aircraft Maintenance Engineer" is Aviation, not Engineering;
# "Software Project Manager" is a Project Manager, not a Software Developer. Titles only:
# descriptions mention too many neighbouring roles to be reliable.
_ROLE_RULES: list[tuple[str, re.Pattern]] = [
    ("Medical Laboratory", re.compile(
        r"\bbiomedical scien|\bmedical lab|\bclinical lab|\blaborato?ry (technician|technologist|scientist|assistant|associate)|"
        r"\blab (technician|technologist|scientist|assistant)|\bmedical technologist|\bphlebotom|(?<!speech )(?<!language )(?<!speech-language )\bpatholog|\bhaematolog|"
        r"\bhematolog|\bhistolog|\bcytolog|\bmicrobiolog|\bblood (bank|sciences?)|\btransfusion|\bclinical scientist|"
        r"\bmlso\b|\bmlt\b|\bmls\b|\bcytogenetic|\bvirolog|\bimmunolog|\bbiochemist", re.I)),
    ("Aviation", re.compile(
        r"\bpilot\b|\bfirst officer\b|\bcaptain\b|\bcabin crew\b|\bflight (attendant|dispatcher|operations|engineer|instructor)|"
        r"\baircraft\b|\baviation\b|\bairline\b|\bairport\b|\bavionic|\bair traffic\b|\bb1\b|\bb2\b|\bpart[- ]?(66|145)\b|"
        r"\bairworthiness\b|\baerospace\b|\bground handling\b|\bramp agent\b|\bairside\b", re.I)),
    ("DevOps & Cloud", re.compile(
        r"\bdevops\b|\bdevsecops\b|\bsite reliability\b|\bsre\b|\bplatform engineer|\bcloud (engineer|architect|"
        r"developer|consultant|specialist|operations|infrastructure)|\binfrastructure engineer|\bkubernetes\b|"
        r"\b(aws|azure|gcp) (engineer|architect|developer|consultant)|\bbuild (and|&) release\b|\brelease engineer", re.I)),
    ("Data Science & AI", re.compile(
        r"\bdata scien|\bmachine learning\b|\bml (engineer|scientist|researcher|ops)\b|\bmlops\b|\bai (engineer|scientist|"
        r"researcher|specialist|developer)\b|\bartificial intelligence\b|\bdeep learning\b|\bcomputer vision\b|\bnlp\b|"
        r"\bllm\b|\bdata engineer|\banalytics engineer|\bapplied scientist\b|\bquantitative researcher\b|"
        r"\bstatistician\b|\bbig data\b|\b(ml|ai|genai)\b|\bgenerative\b", re.I)),
    ("Data Analyst", re.compile(
        r"\bdata analy|\bbi (analyst|developer|engineer)|\bbusiness intelligence\b|\binsights? analyst|\breporting analyst|"
        r"\banalytics (analyst|manager|lead|specialist|consultant)|\bpower ?bi\b|\btableau\b|\bmi analyst|"
        r"\bmanagement information\b|\bproduct analyst|\bmarketing analyst|\bpricing analyst|\bperformance analyst|"
        r"\bdata (quality|governance|visuali[sz]ation|management|steward)|\bsql analyst|\bcommercial analyst|"
        r"\bdatenanalyst|\banalyste (de )?donn[ée]es", re.I)),
    ("Business Analyst", re.compile(
        r"\bbusiness (systems? )?analys|\bbusiness process analys|\bprocess analyst|\bfunctional analyst|\bsystems analyst|"
        r"\brequirements analyst|\bproduct owner\b|\bbusiness architect", re.I)),
    ("Application Support", re.compile(
        r"\bapplications? support|\bproduction support|\bapplication (analyst|specialist|administrator|engineer)|"
        r"\bapplications? manag(er|ement) support|\b(l2|l3|2nd line|second line|3rd line|third line) (application|app)|"
        r"\bsystems? support (analyst|engineer|specialist)|\bsoftware support|\bproduct support (engineer|specialist|analyst)|"
        r"\bsupport analyst|\bincident (manager|analyst)|\bservice (delivery|operations) analyst|\berp (support|analyst)|"
        r"\b(sap|oracle|dynamics|epic|cerner) (support|analyst|consultant|specialist)", re.I)),
    ("IT Support", re.compile(
        r"\bit support|\bservice ?desk\b|\bhelp ?desk\b|\bdesktop support|\bit technician|\bit (officer|engineer|specialist|"
        r"administrator|analyst|assistant|coordinator|manager|operations)|\btechnical support|\b(1st|2nd|first|second) line|"
        r"\bend user (support|computing|services)|\bsystems? administrator|\bsysadmin\b|\bnetwork (administrator|engineer|"
        r"technician|support|analyst)|\binfrastructure (support|analyst|technician)|\bict (technician|support|officer|engineer)|"
        r"\bdeskside\b|\bfield (service|support) (engineer|technician)|\bit field\b|\bcyber ?security (analyst|engineer)|"
        r"\bsecurity (analyst|operations)|\bsoc analyst|\badministrateur (syst|r[ée]seau)|\bsystemadministrator|"
        r"\bit-support|\bsupport informatique|\btechnicien (informatique|support)", re.I)),
    ("Project Manager", re.compile(
        r"\bproject (manag|lead|coordinat|director|officer|controller|support)|\bprogramme (manag|director|lead|coordinat)|"
        r"\bprogram (manag|director|lead|coordinat)|\bpmo\b|\bdelivery (manager|lead|director)|\bscrum ?master\b|"
        r"\bagile (coach|delivery|lead)|\bportfolio manag|\bproject engineer|\bproject planner|\bimplementation manager|"
        r"\btransformation (manager|lead|director)|\bchange manager|\bproduct manag", re.I)),
    ("HR & Recruitment", re.compile(
        r"(?<!/)(?<!per )\bhr\b|\bhuman resources\b|\bpeople (partner|business partner|operations|advisor|adviser|manager|director|lead|"
        r"coordinator|specialist|team)|\btalent (acquisition|partner|manager|lead|specialist)|\brecruit(er|ment|ing)\b|"
        r"\bresourcing\b|\blearning (and|&) development\b|\bl&d\b|\bemployee relations\b|\bcompensation (and|&) benefits\b|"
        r"\breward (manager|analyst|specialist)|\bworkforce (planner|planning|manager)|\bonboarding (specialist|coordinator)|"
        r"\bhris\b|\bpeople ops\b|\borganisational development\b|\btraining (manager|coordinator|officer)", re.I)),
    ("Digital Marketing", re.compile(
        r"\bdigital marketing\b|\bseo\b|\bsem\b|\bppc\b|\bpaid (media|search|social)|\bsocial media\b|\bcontent (marketing|"
        r"manager|strategist|writer|creator|executive|specialist|designer)|\bperformance marketing|\bgrowth (marketing|"
        r"manager|lead|hacker)|\bcrm (marketing|manager|executive|specialist)|\bemail marketing|\bmarketing (executive|"
        r"manager|specialist|coordinator|assistant|officer|lead|director|analyst|automation|operations|associate)|"
        r"\becommerce (manager|executive|specialist)|\be-commerce\b|\bbrand (manager|executive|marketing)|\bcopywriter\b|"
        r"\bcommunications (officer|manager|executive|specialist)|\bdigital (content|campaign|media|communications)|"
        r"\baffiliate (marketing|manager)|\bproduct marketing", re.I)),
    ("Finance & Accounting", re.compile(
        r"\baccount(ant|ing|s (assistant|payable|receivable|manager|officer|semi))|\bfinanc(e|ial)\b|\baudit|\btax\b|"
        r"\bactuar|\bfp&a\b|\bcontroller\b|\bcomptroller\b|\bbookkeep|\bpayroll\b|\btreasury\b|\bcredit (analyst|controller|"
        r"risk|manager)|\bcfo\b|\binvestment (analyst|associate|banking)|\bquant(itative)? analyst|\bacca\b|\bcima\b|"
        r"\baca\b|\bcpa\b|\bbilling (specialist|analyst)|\bcost (accountant|analyst|controller)|\bvaluation|\bunderwriter", re.I)),
    ("Logistics & Supply Chain", re.compile(
        r"\blogistic|\bsupply chain\b|\bwarehouse\b|\bprocurement\b|\bpurchas(ing|er)\b|\bbuyer\b|\bsourcing\b|"
        r"\btransport (planner|manager|coordinator|analyst)|\bfreight\b|\bshipping\b|\binventory\b|\bdistribution\b|"
        r"\bfleet (manager|coordinator)|\bdemand plann|\bsupply plann|\bmaterials? (planner|manager|controller)|"
        r"\bimport(s|er|ing)?\b|\bexport(s|er|ing)?\b|\bcustoms\b|\bfulfil?ment\b|\bdispatch|\bplanner\b|\bs&op\b|\bcategory manager|\bstock controller", re.I)),
    ("Software Developer", re.compile(
        r"\bsoftware\b|\bdeveloper\b|\bprogrammer\b|\bentwickler|\bd[ée]veloppeu|\bdesarrollador|\bprogramista\b|\bfull.?stack\b|\bfront.?end\b|\bback.?end\b|\bweb (developer|engineer)|"
        r"\bmobile (developer|engineer)|\b(ios|android)\b|\b(java|python|\.net|c#|c\+\+|golang|go|rust|ruby|php|node(\.js)?|"
        r"react|angular|javascript|typescript|scala|kotlin|swift) (developer|engineer)|\bqa (engineer|analyst|tester)|"
        r"\btest (engineer|analyst|automation)|\bsdet\b|\bsoftware tester|\bembedded (software|engineer|developer)|"
        r"\bfirmware\b|\bgame (developer|programmer)|\bsolutions? architect|\bsoftware architect|\btechnical lead\b|"
        r"\btech lead\b|\bengineering manager\b|\bproduct engineer\b|\bsecurity engineer\b|\bapi\b", re.I)),
    ("Engineering", re.compile(
        r"\bengineer|\bengineering\b|\bmechanical\b|\belectrical\b|\bcivil\b|\bstructural\b|\bchemical\b|\bprocess (engineer|"
        r"technician)|\bmanufacturing\b|\bmaintenance (technician|engineer|manager)|\bdesign engineer|\bcad\b|"
        r"\bquantity surveyor|\bsurveyor\b|\bgeotechnical|\bhvac\b|\bcommissioning\b|\bquality (engineer|manager|inspector)|"
        r"\bhealth (and|&) safety\b|\bmechatronic|\brobotics\b|\bautomation (engineer|technician)|\bplc\b|"
        r"\binstrumentation\b|\bproduction (engineer|manager|supervisor)|\btechnician\b|\barchitect(ural)? (technologist|assistant)|"
        r"\bing[ée]nieur|\bingeniero|\btechnicien|\btechniker\b|\binżynier|\binsinööri|\behs\b|\bhse\b", re.I)),
]


def classify_role(job: Job) -> str:
    for role, rx in _ROLE_RULES:
        if rx.search(job.title):
            return role
    return "Other"


# ----------------------------------------------------------------------------- region (Scotland, Dubai)
_SCOTLAND_RE = re.compile(
    r"\bscotland\b|\bscottish\b|\bglasgow\b|\bedinburgh\b|\baberdeen(shire)?\b|\bdundee\b|\binverness\b|\bstirling\b|"
    r"\bst andrews\b|\bpaisley\b|\blivingston\b|\bfalkirk\b|\bkilmarnock\b|\bayr(shire)?\b|\bdumfries\b|\bfife\b|"
    r"\bkirkcaldy\b|\bdunfermline\b|\bmotherwell\b|\bhamilton\b|\bcumbernauld\b|\beast kilbride\b|\bhighland\b|"
    r"\blanarkshire\b|\blothian\b|\bperth(shire)?\b|\bmoray\b|\belgin\b|\bshetland\b|\borkney\b|\bwestern isles\b|"
    r"\bclydebank\b|\bgreenock\b|\bnhs (lothian|greater glasgow|grampian|tayside|highland|fife|lanarkshire|ayrshire|"
    r"forth valley|borders|dumfries|shetland|orkney|western isles|golden jubilee|education for scotland|24)\b|"
    r"\bscottish borders\b", re.I)
_DUBAI_RE = re.compile(r"\bdubai\b|\bjebel ali\b|\bdifc\b|\bdmcc\b", re.I)
_ABU_DHABI_RE = re.compile(r"\babu dhabi\b|\bal ain\b", re.I)


def classify_region(job: Job) -> str:
    text = f"{job.location} {job.company}"
    if job.country == "GB" and _SCOTLAND_RE.search(text):
        return "Scotland"
    if job.country == "AE":
        if _DUBAI_RE.search(text):
            return "Dubai"
        if _ABU_DHABI_RE.search(text):
            return "Abu Dhabi"
    return ""


# ----------------------------------------------------------------------------- English-speaking
ENGLISH_SPEAKING_COUNTRIES = {"GB", "IE", "US", "MT"}
_LANGS = (r"german|dutch|french|swedish|finnish|polish|spanish|luxembourgish|italian|arabic|portuguese|danish|"
          r"norwegian|czech|flemish|catalan|hungarian|romanian|greek|estonian|latvian|lithuanian|slovak|slovenian")
_LANG_REQUIRED = [re.compile(p, re.I) for p in (
    rf"\b(fluent|fluency|native|proficien\w*|business[- ]level|professional|excellent|very good|good|strong|working|"
    rf"advanced|full) (command of |knowledge of |level of |skills in |proficiency in |in |written and spoken |spoken and "
    rf"written )*({_LANGS})\b",
    rf"\b({_LANGS})( language)?( skills| proficiency| fluency)? (is |are )?(required|essential|mandatory|a must|necessary|needed)",
    rf"\b({_LANGS})\s*\(?(c1|c2|b2)\b",
    rf"\b(must|need to|required to|should) (speak|be fluent in|have fluent) ({_LANGS})\b",
    rf"\b(fluent|fluency|native|proficien\w*|business[- ]level|excellent|strong|good) (in )?english (and|&|as well as|plus) ({_LANGS})\b",
    rf"\b({_LANGS})[- ]speak(ing|er)\b",
)]
_LANG_OPTIONAL = re.compile(
    rf"({_LANGS})[^.;]{{0,60}}\b(is |would be |are )?(a plus|an advantage|advantageous|nice to have|beneficial|desirable|"
    rf"a bonus|preferred|not required|helpful|appreciated)", re.I)
_EN_STOPWORDS = {"the", "and", "you", "with", "for", "our", "will", "are", "your", "this", "that", "have", "we",
                 "to", "of", "is", "be", "as", "an", "who", "from", "experience", "about", "what", "role"}
# Common words of the other languages adverts are written in (none of them English words).
_FOREIGN_STOPWORDS = {
    "und", "der", "das", "wir", "sie", "mit", "für", "ist", "bei", "eine", "auf", "dich", "du", "ihre", "unsere",
    "le", "la", "les", "des", "et", "pour", "nous", "vous", "une", "dans", "est", "du", "au", "avec", "sur",
    "het", "een", "van", "voor", "zijn", "jij", "wij", "ons", "naar", "bij", "ook", "je", "jouw",
    "och", "att", "för", "som", "är", "vi", "med", "av", "har", "till", "det", "en", "ett",
    "el", "los", "las", "para", "con", "y", "una", "del", "por", "tu", "nuestro", "que",
    "się", "oraz", "dla", "jest", "nas", "jako", "pracy", "ja", "että", "sekä", "ole", "työ", "il", "di", "per", "che",
    "og", "på", "af", "و", "في", "من",
}
_WORD_RE = re.compile(r"[^\W\d_]+", re.U)


def _looks_english(text: str) -> bool:
    words = _WORD_RE.findall(text[:2000].lower())
    english = sum(w in _EN_STOPWORDS for w in words)
    foreign = sum(w in _FOREIGN_STOPWORDS for w in words)
    return english >= foreign


def classify_english(job: Job) -> bool:
    """True when an English speaker can do the job: the advert is in English and asks for no other language."""
    text = f"{job.title} {job.description}"
    if not _looks_english(job.description or job.title):
        return False
    required = [m for rx in _LANG_REQUIRED for m in rx.finditer(text)]
    if not required:
        return True
    # "German is a plus" does not make German a requirement.
    return all(_LANG_OPTIONAL.search(text[m.start():m.end() + 80]) for m in required)


# ----------------------------------------------------------------------------- early career: UK Graduate visa (PSW) / US OPT
_EARLY_TITLE_RE = re.compile(
    r"\bgraduate\b|\bgrad\b|\bnew grad|\bentry[- ]level\b|\bjunior\b|\bjr\.?\b|\btrainee\b|\bintern(ship)?\b|"
    r"\bplacement\b|\bearly career|\bassociate (software|engineer|developer|analyst|consultant|data)|"
    r"\b(analyst|engineer|developer|scientist|consultant) (i|1)\b|\bcampus\b|\bstudent\b|\bresidency\b|"
    r"\bfoundation (year|doctor|programme)|\bfy1\b|\bnewly qualified\b|\bect\b|\bpostdoc|\bpost-doctoral\b", re.I)
_PSW_RE = re.compile(
    r"\bgraduate (visa|route)\b|\bpost[- ]study work\b|\bpsw\b|\bgraduate immigration route\b|"
    r"\b(tier 4|student) visa (holders?|to skilled worker)\b|\bswitch(ing)? (from|to) (a |the )?(graduate|skilled worker) visa", re.I)
_OPT_RE = re.compile(
    r"\bstem[- ]opt\b|\bopt ?/ ?cpt\b|\bcpt ?/ ?opt\b|\bopt (students?|candidates?|holders?|eligible|extension|status|"
    r"work authori[sz]ation|ead|visa)\b|\b(on|with|under) (an? )?opt\b|\boptional practical training\b|"
    r"\bcurricular practical training\b|\bf-?1 (visa|students?|opt)\b|\bstem extension\b|\bcap[- ]exempt\b", re.I)
_OPT_NEGATIVE_RE = re.compile(
    r"(not|cannot|can't|unable to|do not|don't|won't) (\w+ ){0,3}(accept|consider|support|hire|sponsor)\w* (\w+ ){0,3}"
    r"(opt|cpt|f-?1|graduate visa|psw)\b", re.I)
_E_VERIFY_RE = re.compile(r"\be-?verify\b", re.I)
# A route named in a negative sentence ("will not sponsor ... (i.e. H1B, F-1 OPT, CPT ...)") is not an invitation.
_NEGATION_RE = re.compile(r"\b(not|no|unable|cannot|can't|won't|neither|nor|ineligible)\b", re.I)


_ABBREV_RE = re.compile(r"\b(?:i\.e|e\.g|etc|u\.s(?:\.a)?|vs|incl|approx|no)\.", re.I)
_CONTRAST_RE = re.compile(r"\b(but|however|although|though)\b", re.I)


def _sentence(text: str, pos: int) -> str:
    start = max(text.rfind(c, 0, pos) for c in ".;!?\n") + 1
    ends = [i for i in (text.find(c, pos) for c in ".;!?\n") if i != -1]
    # "We cannot sponsor, but Graduate visa holders are welcome": only the clause after "but" counts.
    turn = list(_CONTRAST_RE.finditer(text, start, pos))
    return text[turn[-1].end() if turn else start:min(ends) if ends else len(text)]


def classify_early_career(job: Job) -> str:
    """Whether a UK Graduate visa (PSW) or US F-1 OPT holder can realistically take the job.

    * "stated": the advert names the route (Graduate visa / PSW, OPT / STEM OPT / CPT, cap-exempt H-1B).
    * "likely": an entry-level role at an employer that sponsors (UK: licensed or offers sponsorship,
      so the Graduate visa can later switch to Skilled Worker; US: files H-1Bs or is an E-Verify employer,
      which STEM OPT requires).
    """
    if job.country not in ("GB", "US"):
        return ""
    text = f"{job.title} {job.description}"
    if _OPT_NEGATIVE_RE.search(text):
        return ""
    route_re = _PSW_RE if job.country == "GB" else _OPT_RE
    # "(i.e. H1B, F-1 OPT ...)": abbreviation dots must not end the sentence. Same length, so positions hold.
    text = _ABBREV_RE.sub(lambda m: m.group(0).replace(".", " "), text)
    if any(not _NEGATION_RE.search(_sentence(text, m.start())) for m in route_re.finditer(text)):
        return "stated"
    if not _EARLY_TITLE_RE.search(job.title):
        return ""
    if job.sponsorship in ("confirmed", "licensed_sponsor") or (job.country == "US" and _E_VERIFY_RE.search(text)):
        return "likely"
    return ""


# ----------------------------------------------------------------------------- tier & size
@dataclass
class TierRules:
    names: dict[str, tuple[int, str]]        # normalised name -> (tier, size)
    patterns: list[tuple[re.Pattern, int, str]]

    @classmethod
    def load(cls, path: Path) -> "TierRules":
        cfg = json.loads(path.read_text(encoding="utf-8"))
        names: dict[str, tuple[int, str]] = {}
        for tier_key, tier in (("tier1", 1), ("tier2", 2), ("tier3", 3)):
            default_size = cfg.get("default_size", {}).get(tier_key, "unknown")
            for entry in cfg.get(tier_key, []):
                if isinstance(entry, str):
                    entry = {"name": entry}
                names[normalise_company(entry["name"])] = (tier, entry.get("size", default_size))
        patterns = [(re.compile(p["regex"], re.I), int(p["tier"]), p.get("size", "unknown"))
                    for p in cfg.get("patterns", [])]
        return cls(names, patterns)

    def classify(self, job: Job) -> tuple[int, str]:
        key = normalise_company(job.company)
        if key in self.names:
            tier, size = self.names[key]
        else:
            tier, size = 3, "unknown"
            for rx, p_tier, p_size in self.patterns:
                if rx.search(job.company):
                    tier, size = p_tier, p_size
                    break
        if size == "unknown":
            size = _size_from_text(job.description)
        return tier, size


_HEADCOUNT_RE = re.compile(r"(\d{1,3}(?:[,.]\d{3})*|\d+)\s*\+?\s*(?:employees|staff|people|colleagues|team members)", re.I)
_SMALL_HINT_RE = re.compile(r"\b(start-?up|early.stage|seed.funded|series a|small team|sme|boutique)\b", re.I)


def _size_from_text(text: str) -> str:
    """UK Companies Act bands: small < 50, medium 50–249, large 250+."""
    m = _HEADCOUNT_RE.search(text)
    if m:
        n = int(re.sub(r"[,.]", "", m.group(1)))
        if n >= 250:
            return "large"
        if n >= 50:
            return "medium"
        if n > 1:
            return "small"
    if _SMALL_HINT_RE.search(text):
        return "small"
    return "unknown"
