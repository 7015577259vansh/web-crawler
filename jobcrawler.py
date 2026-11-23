#!/usr/bin/env python3
"""
Shared engine for the per-person job crawlers:
    crawler-shakshi.py   crawler-mahi.py   crawler-vansh.py

Each of those files only holds a PROFILE (target levels, roles, experience range)
and calls main(PROFILE). Standard library only.

Common commands (replace 'shakshi' with 'mahi' or 'vansh'):
    python3 crawler-shakshi.py                       # crawl -> jobs-shakshi.csv / .html
    python3 crawler-shakshi.py --new-only            # only openings not seen before
    python3 crawler-shakshi.py --check               # test which boards respond
    python3 crawler-shakshi.py --discover "Postman,Razorpay"
    python3 crawler-shakshi.py --discover-file candidates.txt --write   # grow companies.json
    python3 crawler-shakshi.py --no-exp              # ignore the years-of-experience filter
"""
import argparse
import csv
import html as htmllib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
UA = "Mozilla/5.0 (personal job-search script)"
STATE = {"query": "software engineer", "term": "engineer", "need_desc": False}

# ---------------------------------------------------------------- filters
CITIES = [
    "india", "gurgaon", "gurugram", "noida", "greater noida", "delhi", "new delhi",
    "ncr", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "navi mumbai",
    "chennai", "kolkata", "ahmedabad", "kochi", "jaipur", "chandigarh", "mohali",
    "indore", "coimbatore", "thiruvananthapuram", "trivandrum", "nagpur", "vadodara",
]
LOC_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in CITIES) + r")\b", re.I)
NOT_INDIA_RE = re.compile(r"\b(indiana|indianapolis)\b", re.I)

# a title must look like a software / data / platform role...
DEFAULT_ROLE = (
    r"\b(software|developer|programmer|sde|swe|backend|back-end|full[\s-]?stack|platform|"
    r"data engineer|devops|sre|site reliability|infrastructure|cloud|java|python|golang|"
    r"distributed|systems? engineer|mts|member of technical staff|machine learning|"
    r"ml engineer|ai engineer)\b"
)
# ...and must not be one of these for anybody
BASE_EXCLUDE = (
    r"\b(manager|director|head of|vp|recruiter|sales|marketing|designer|customer success|"
    r"account (executive|manager)|technical writer|program manager|solutions? (architect|engineer)|"
    r"support engineer|in test|sdet|qa|quality assurance|test engineer|test automation)\b"
)


GENERIC_SKIP = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|junior|jr\.?|intern|trainee|graduate|associate|entry|fresher|"
    r"apprentice|i|1|iii|3|iv|4|5|v)\b", re.I)


def location_ok(loc):
    return bool(LOC_RE.search(NOT_INDIA_RE.sub("", loc or "")))


def make_matcher(p, extra_kw=None, extra_ex=None):
    level = re.compile(p["level"], re.I)
    role_src = DEFAULT_ROLE
    if p.get("role_extra"):
        role_src = DEFAULT_ROLE[:-3] + p["role_extra"] + r")\b"
    role = re.compile(role_src, re.I)
    ex_src = BASE_EXCLUDE + ("|" + p["exclude"] if p.get("exclude") else "")
    ex = re.compile(ex_src, re.I)
    kw = re.compile(extra_kw, re.I) if extra_kw else None
    xx = re.compile(extra_ex, re.I) if extra_ex else None
    generic_on = bool(p.get("generic"))
    generic_role = re.compile(p["generic_role"], re.I) if p.get("generic_role") else role

    def match(job):
        t = job["title"]
        if ex.search(t) or not role.search(t):
            return False
        if not level.search(t):
            # Untitled-level roles (e.g. plain "Software Engineer") are only kept when the
            # profile opts in; apply_exp() then requires the description to confirm the experience.
            if not generic_on or GENERIC_SKIP.search(t) or not generic_role.search(t):
                return False
            job["_generic"] = True
        if kw and not kw.search(t):
            return False
        if xx and xx.search(t):
            return False
        return location_ok(job["location"])
    return match


# ---------------------------------------------------------------- experience
TAG_RE = re.compile(r"<[^>]+>")
YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*(?:\+|plus)?\s*)?(?:years?|yrs?)\b", re.I)


def clean(t):
    t = htmllib.unescape(t or "")
    t = TAG_RE.sub(" ", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t)).strip()


def required_years(raw):
    """Best-effort: highest 'N+ years ... experience' figure in the description."""
    text = clean(raw)
    if not text:
        return None
    vals = []
    for m in YEARS_RE.finditer(text):
        lo = int(m.group(1))
        if lo > 25:
            continue
        ctx = text[max(0, m.start() - 100): m.end() + 100].lower()
        if "experience" in ctx:
            vals.append(lo)
    return max(vals) if vals else None


def apply_exp(jobs, p, drop_unknown):
    lo, hi = p.get("exp_min"), p.get("exp_max")
    gtext = re.compile(p["generic_text"], re.I) if p.get("generic_text") else None
    kept, dropped = [], 0
    for j in jobs:
        raw = j.pop("desc", "")
        req = required_years(raw)
        j["exp"] = req
        generic = j.pop("_generic", False)
        in_range = req is not None and (lo is None or req >= lo) and (hi is None or req <= hi)
        if generic:                       # untitled role: keep only if the description confirms it
            if in_range or (req is None and gtext and gtext.search(clean(raw))):
                kept.append(j)
            else:
                dropped += 1
        elif lo is None and hi is None:
            kept.append(j)
        elif req is None:
            if drop_unknown:
                dropped += 1
            else:
                kept.append(j)
        elif in_range:
            kept.append(j)
        else:
            dropped += 1
    return kept, dropped


# ---------------------------------------------------------------- http
def make_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for path in ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem"):
        if Path(path).exists():
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


SSL_CTX = make_ssl_context()


def http(url, data=None, headers=None, timeout=30, retries=3):
    if STATE.get("fast"):          # discovery: fail fast, do not retry dead guesses
        retries, timeout = 0, min(timeout, 12)
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404, 422):
                raise
            last = e
        except Exception as e:
            last = e
        time.sleep((6 if getattr(last, "code", 0) == 429 else 1.5) * (attempt + 1))
    raise last


def J(title, location, url, desc=""):
    return {"title": title or "", "location": location or "", "url": url or "", "desc": desc or ""}


# ---------------------------------------------------------------- fetchers
def f_greenhouse(e):
    suffix = "?content=true" if STATE["need_desc"] else ""
    d = http(f"https://boards-api.greenhouse.io/v1/boards/{e['slug']}/jobs{suffix}")
    for j in d.get("jobs", []):
        yield J(j.get("title"), (j.get("location") or {}).get("name"), j.get("absolute_url"), j.get("content"))


def f_lever(e):
    for j in http(f"https://api.lever.co/v0/postings/{e['slug']}?mode=json"):
        c = j.get("categories") or {}
        locs = [c.get("location")] + list(c.get("allLocations") or [])
        desc = " ".join([j.get("descriptionPlain") or ""] +
                        [(x.get("content") or "") for x in (j.get("lists") or [])] +
                        [j.get("additionalPlain") or ""])
        yield J(j.get("text"), "; ".join(dict.fromkeys(x for x in locs if x)), j.get("hostedUrl"), desc)


def f_ashby(e):
    d = http(f"https://api.ashbyhq.com/posting-api/job-board/{e['slug']}")
    for j in d.get("jobs", []):
        locs = [j.get("location")] + [l.get("location") for l in (j.get("secondaryLocations") or [])]
        yield J(j.get("title"), "; ".join(x for x in locs if x), j.get("jobUrl"),
                j.get("descriptionPlain") or j.get("descriptionHtml"))


def f_smartrecruiters(e):
    off = 0
    while off < 1000:
        q = urllib.parse.urlencode({"q": STATE["term"], "country": "in", "limit": 100, "offset": off})
        d = http(f"https://api.smartrecruiters.com/v1/companies/{e['slug']}/postings?{q}")
        items = d.get("content", [])
        for j in items:
            l = j.get("location") or {}
            country = "India" if (l.get("country") or "").lower() == "in" else l.get("country")
            loc = ", ".join(x for x in [l.get("city"), l.get("region"), country] if x)
            yield J(j.get("name"), loc, f"https://jobs.smartrecruiters.com/{e['slug']}/{j.get('id')}")
        if len(items) < 100:
            break
        off += 100


def f_workday(e):
    host, tenant, site = e["host"], e["tenant"], e["site"]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    off, total = 0, None
    while off < 400 and (total is None or off < total):
        d = http(api, data={"appliedFacets": {}, "limit": 20, "offset": off, "searchText": STATE["query"]})
        total = d.get("total", 0)
        posts = d.get("jobPostings", [])
        if not posts:
            break
        for j in posts:
            yield J(j.get("title"), j.get("locationsText"), f"https://{host}/en-US/{site}{j.get('externalPath', '')}")
        off += 20


def f_workable(e):
    d = http(f"https://apply.workable.com/api/v1/widget/accounts/{e['slug']}?details=true")
    for j in d.get("jobs", []):
        loc = ", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x)
        yield J(j.get("title"), loc, j.get("url") or j.get("shortlink"), j.get("description"))


def f_recruitee(e):
    d = http(f"https://{e['slug']}.recruitee.com/api/offers/")
    for j in d.get("offers", []):
        loc = j.get("location") or ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        yield J(j.get("title"), loc, j.get("careers_url"),
                (j.get("description") or "") + " " + (j.get("requirements") or ""))


def f_atlassian(e):
    d = http("https://www.atlassian.com/endpoint/careers/listings")
    for j in d if isinstance(d, list) else d.get("listings", []):
        locs = j.get("locations") or j.get("location") or []
        if isinstance(locs, str):
            locs = [locs]
        url = j.get("applyUrl") or (j.get("portalJobPost") or {}).get("portalUrl") or ""
        desc = " ".join(str(j.get(k) or "") for k in
                        ("overview", "responsibilities", "qualifications", "preferredQualifications"))
        yield J(j.get("title"), "; ".join(locs), url, desc)


def f_amazon(e):
    seen = set()
    for query in dict.fromkeys([STATE["query"], "software development engineer"]):
        off = 0
        while off < 1500:
            q = urllib.parse.urlencode({"base_query": query, "country": "IND",
                                        "result_limit": 100, "offset": off, "sort": "recent"})
            d = http(f"https://www.amazon.jobs/en/search.json?{q}")
            jobs = d.get("jobs", [])
            fresh = [j for j in jobs if j.get("job_path") not in seen]
            for j in fresh:
                seen.add(j.get("job_path"))
                yield J(j.get("title"), j.get("normalized_location") or j.get("location"),
                        "https://www.amazon.jobs" + j.get("job_path", ""),
                        (j.get("basic_qualifications") or "") + " " + (j.get("description") or ""))
            if not fresh:
                break
            off += len(jobs)
            time.sleep(0.5)


def f_adzuna(e):
    """Aggregator covering thousands of Indian employers. Needs a free key from developer.adzuna.com:
         export ADZUNA_APP_ID=...   export ADZUNA_APP_KEY=..."""
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise RuntimeError("set ADZUNA_APP_ID and ADZUNA_APP_KEY")
    seen = set()
    for city in ("gurgaon", "noida", "delhi", "bangalore", "hyderabad", "pune", "mumbai", "chennai"):
        for page in range(1, 6):
            q = urllib.parse.urlencode({"app_id": app_id, "app_key": app_key, "what": STATE["query"],
                                        "where": city, "results_per_page": 50, "sort_by": "date",
                                        "max_days_old": 45})
            try:
                d = http(f"https://api.adzuna.com/v1/api/jobs/in/search/{page}?{q}")
            except urllib.error.HTTPError:
                if page == 1:
                    raise
                break
            results = d.get("results", [])
            for j in results:
                if j.get("id") in seen:
                    continue
                seen.add(j.get("id"))
                job = J(clean(j.get("title")), (j.get("location") or {}).get("display_name"),
                        j.get("redirect_url"), j.get("description"))
                job["company"] = (j.get("company") or {}).get("display_name") or "(via Adzuna)"
                yield job
            if len(results) < 50:
                break


def f_microsoft(e):
    # UNVERIFIED endpoint (Eightfold-based careers site). Fails soft.
    host = "https://apply.careers.microsoft.com"
    start = 0
    while start < 500:
        q = urllib.parse.urlencode({"domain": "microsoft.com", "query": STATE["query"],
                                    "location": "India", "start": start})
        d = http(f"{host}/api/pcsx/search?{q}")
        data = d.get("data") or {}
        pos = data.get("positions") or []
        for j in pos:
            locs = j.get("locations") or j.get("standardizedLocations") or []
            if isinstance(locs, str):
                locs = [locs]
            url = j.get("positionUrl") or f"/careers/job/{j.get('id')}"
            yield J(j.get("name") or j.get("title"), "; ".join(locs), url if url.startswith("http") else host + url)
        if not pos:
            break
        time.sleep(1.5)
        start += len(pos)
        if start >= data.get("count", 0):
            break


FETCHERS = {
    "greenhouse": f_greenhouse, "lever": f_lever, "ashby": f_ashby,
    "smartrecruiters": f_smartrecruiters, "workday": f_workday,
    "workable": f_workable, "recruitee": f_recruitee,
    "atlassian": f_atlassian, "amazon": f_amazon, "microsoft": f_microsoft, "adzuna": f_adzuna,
}
DISCOVERABLE = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee")
SINGLETONS = ("atlassian", "amazon", "microsoft", "adzuna")


# ---------------------------------------------------------------- company list
def load_entries(path):
    cfg = json.loads(Path(path).read_text())
    out = []
    for ats, entries in cfg.items():
        if ats.startswith("_") or ats not in FETCHERS:
            continue
        if ats in SINGLETONS:
            if entries:
                out.append((ats, {"name": ats.title(), "slug": ats}))
            continue
        seen_keys = set()
        for x in entries:
            e = {"slug": x, "name": x} if isinstance(x, str) else dict(x)
            e.setdefault("name", e.get("slug") or e.get("tenant"))
            k = (e.get("slug") or e.get("tenant", "") + "/" + e.get("site", "")).lower()
            if k in seen_keys:
                continue
            seen_keys.add(k)
            out.append((ats, e))
    if os.environ.get("ADZUNA_APP_ID") and not any(a == "adzuna" for a, _ in out):
        out.append(("adzuna", {"name": "Adzuna", "slug": "adzuna"}))
    return out


def parse_careers_url(url):
    """Recognise a company's careers/apply URL and return (ats, entry)."""
    u = urllib.parse.urlparse(url.strip())
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    if host.endswith("greenhouse.io") and parts and parts[0] not in ("embed", "v1"):
        return "greenhouse", parts[0]
    if host == "jobs.lever.co" and parts:
        return "lever", parts[0]
    if host == "jobs.ashbyhq.com" and parts:
        return "ashby", parts[0]
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and parts:
        return "smartrecruiters", parts[0]
    if host == "apply.workable.com" and parts:
        return "workable", parts[0]
    if host.endswith(".recruitee.com"):
        return "recruitee", host.split(".")[0]
    if host.endswith(".myworkdayjobs.com"):
        segs = [p for p in parts if not re.fullmatch(r"[a-z]{2}-[A-Za-z]{2}", p)]
        if segs:
            tenant = host.split(".")[0]
            return "workday", {"name": tenant.title(), "host": host, "tenant": tenant, "site": segs[0]}
    return None, None


def add_urls(urls, companies_path):
    path = Path(companies_path)
    cfg = json.loads(path.read_text())
    for url in urls:
        if not url.strip():
            continue
        ats, entry = parse_careers_url(url)
        if not ats:
            print(f"  SKIP   {url.strip()}  (not a Greenhouse/Lever/Ashby/SmartRecruiters/Workable/Recruitee/Workday link)")
            continue
        lst = cfg.setdefault(ats, [])
        key = (entry if isinstance(entry, str) else entry["tenant"] + "/" + entry["site"]).lower()
        have = {(x if isinstance(x, str) else x.get("tenant", "") + "/" + x.get("site", "")).lower() for x in lst}
        if key in have:
            print(f"  EXISTS {ats}: {key}")
        else:
            lst.append(entry)
            print(f"  ADDED  {ats}: {key}")
    path.write_text(json.dumps(cfg, indent=2))


NAME_STOP = {"inc", "ltd", "limited", "pvt", "corp", "corporation", "company", "co", "india", "global",
             "tech", "technologies", "technology", "systems", "software", "group", "labs", "services",
             "solutions", "holdings", "pbc"}


def slug_variants(name):
    """Likely board slugs: full name, hyphenated, and the name without words like 'Inc' / 'India' / 'Global'."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    core = [w for w in words if w not in NAME_STOP] or words
    out = ["".join(words), "-".join(words), "".join(core), "-".join(core), re.sub(r"[^A-Za-z0-9]", "", name)]
    return [v for v in dict.fromkeys(out) if v]


def probe(name):
    base = name.strip()
    low = base.lower()
    cands = slug_variants(base)
    for ats in DISCOVERABLE:
        for slug in cands:
            if not slug:
                continue
            try:
                jobs = list(FETCHERS[ats]({"slug": slug, "name": name}))
            except Exception:
                continue
            n = len(jobs)
            ind = sum(1 for j in jobs if location_ok(j["location"]))
            if n > 0 and (ind > 0 or not STATE.get("india_only", True)):
                return name, [(ats, slug, n, ind)]      # first system that works is enough
    if STATE.get("workday"):
        r = probe_workday(base)
        if r:
            return name, [r]
    return name, []


def final_url(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.geturl()


def probe_workday(name):
    """Guess <name>.wdN.myworkdayjobs.com, follow its redirect to learn the site name, then verify."""
    tenants = list(dict.fromkeys(re.sub(r"[^a-z0-9]", "", v.lower()) for v in slug_variants(name)[::2]))
    for tenant, n in [(t, n) for t in tenants if t for n in (5, 1, 3, 12, 103, 501, 2, 4)]:
        host = f"{tenant}.wd{n}.myworkdayjobs.com"
        try:
            ats, entry = parse_careers_url(final_url(f"https://{host}/"))
        except Exception:
            continue
        if ats != "workday":
            continue
        entry["name"] = name
        try:
            d = http(f"https://{entry['host']}/wday/cxs/{entry['tenant']}/{entry['site']}/jobs",
                     data={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "India software engineer"})
        except Exception:
            continue
        posts = d.get("jobPostings", [])
        ind = sum(1 for j in posts if location_ok(j.get("locationsText")))
        if d.get("total", 0) > 0 and (ind > 0 or not STATE.get("india_only", True)):
            return ("workday", entry, d.get("total", 0), ind)
    return None


def discover(names, companies_path, write, workers):
    STATE["need_desc"] = False
    STATE["term"] = "engineer"
    STATE["fast"] = True
    names = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    path = Path(companies_path)
    total, done, added, missing = len(names), 0, 0, []
    ex = ThreadPoolExecutor(max_workers=max(workers, 24))
    futs = [ex.submit(probe, n) for n in names]
    try:
        for f in as_completed(futs):
            name, found = f.result()
            done += 1
            if not found:
                missing.append(name)
                print(f"[{done}/{total}] {name}: no supported board with India jobs", flush=True)
                continue
            for ats, slug, n, ind in found:
                shown = slug if isinstance(slug, str) else f"{slug['host']}/{slug['site']}"
                print(f"[{done}/{total}] FOUND {name}: {ats} -> \"{shown}\" ({n} jobs, {ind} in India)", flush=True)
                if write:   # saved immediately, so Ctrl+C never loses progress
                    cfg = json.loads(path.read_text())
                    lst = cfg.setdefault(ats, [])
                    keyf = lambda x: (x if isinstance(x, str) else x.get("tenant", "") + "/" + x.get("site", "")).lower()
                    have = {keyf(x) for x in lst}
                    if keyf(slug) not in have:
                        lst.append(slug)
                        path.write_text(json.dumps(cfg, indent=2))
                        added += 1
    except KeyboardInterrupt:
        print("\nStopped early. Boards found so far are already saved.")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    print(f"\nChecked {done}/{total} names. {'Added ' + str(added) + ' boards to ' + path.name + '.' if write else 'Nothing written (add --write).'}")
    print("Boards are guessed from company names, so skim the FOUND lines for look-alike names.")


# ---------------------------------------------------------------- crawl
def run_one(ats, e, match):
    try:
        jobs = [{"company": e["name"], "source": ats, **j} for j in FETCHERS[ats](e)]
    except urllib.error.HTTPError as ex:
        return e["name"], ats, [], 0, f"HTTP {ex.code}"
    except Exception as ex:
        return e["name"], ats, [], 0, str(ex)[:80]
    return e["name"], ats, [j for j in jobs if match(j)], len(jobs), None


def main(profile):
    name = profile["name"]
    ap = argparse.ArgumentParser(description=f"Job crawler for {name}")
    ap.add_argument("--companies", default=str(HERE / "companies.json"))
    ap.add_argument("--new-only", action="store_true", help="only show openings not seen on earlier runs")
    ap.add_argument("--check", action="store_true", help="only test which boards respond")
    ap.add_argument("--no-exp", action="store_true", help="skip the years-of-experience filter")
    ap.add_argument("--drop-unknown", action="store_true",
                    help="also drop jobs whose experience requirement could not be read")
    ap.add_argument("--keyword", help="regex the title must match, e.g. 'java|backend'")
    ap.add_argument("--exclude", help="regex that rejects a title, e.g. 'frontend|data'")
    ap.add_argument("--discover", help="comma-separated company names to look up")
    ap.add_argument("--discover-file", help="text file with one company name per line")
    ap.add_argument("--add-url", help="comma-separated careers-page links to add, e.g. a company's Workday or Lever URL")
    ap.add_argument("--add-url-file", help="text file with one careers-page link per line (# comments allowed)")
    ap.add_argument("--with-workday", action="store_true",
                    help="with --discover*: also try to find each company's Workday careers site (slower)")
    ap.add_argument("--any-location", action="store_true", help="with --discover*: keep boards even with no India jobs")
    ap.add_argument("--write", action="store_true", help="with --discover*: add found boards to companies.json")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    STATE["query"] = profile.get("query", "software engineer")
    STATE["term"] = profile.get("search_term", STATE["query"].split()[0])
    has_exp = profile.get("exp_min") is not None or profile.get("exp_max") is not None
    STATE["need_desc"] = has_exp and not args.no_exp and not args.check

    STATE["india_only"] = not args.any_location
    STATE["workday"] = args.with_workday
    if args.add_url or args.add_url_file:
        urls = args.add_url.split(",") if args.add_url else []
        if args.add_url_file:
            urls += [l.strip() for l in Path(args.add_url_file).read_text().splitlines()
                     if l.strip() and not l.strip().startswith("#")]
        add_urls(urls, args.companies)
        return

    if args.discover or args.discover_file:
        names = []
        if args.discover:
            names += args.discover.split(",")
        if args.discover_file:
            names += [l.strip() for l in Path(args.discover_file).read_text().splitlines()
                      if l.strip() and not l.startswith("#")]
        discover(names, args.companies, args.write, args.workers)
        return

    entries = load_entries(args.companies)
    match = make_matcher(profile, args.keyword, args.exclude)

    results, boards, failed = [], [], []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run_one, a, e, match) for a, e in entries]
        for f in as_completed(futs):
            n, ats, jobs, fetched, err = f.result()
            if err:
                failed.append((n, ats, err))
            else:
                boards.append((n, ats, fetched, len(jobs)))
                results.extend(jobs)

    if args.check:
        print(f"{len(boards)} boards OK, {len(failed)} failed\n")
        for n, ats, fetched, matched in sorted(boards, key=lambda b: b[0].lower()):
            print(f"  OK    {n} [{ats}] {fetched} jobs fetched, {matched} match title/location filters")
        for n, ats, err in sorted(failed):
            print(f"  FAIL  {n} [{ats}] {err}")
        return

    before = len(results)
    if has_exp and not args.no_exp:
        results, dropped = apply_exp(results, profile, args.drop_unknown)
    else:
        results = [j for j in results if not j.get("_generic")]
        for j in results:
            j.pop("desc", None)
            j["exp"] = None
        dropped = 0

    uniq = {}
    for j in results:
        key = (j["company"].lower(), j["title"].strip().lower(), j["location"].strip().lower())
        uniq.setdefault(key, j)
    results = list(uniq.values())

    seen_path = HERE / f"seen-{name}.json"
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    for j in results:
        j["is_new"] = j["url"] not in seen
    seen_path.write_text(json.dumps(sorted(seen | {j["url"] for j in results})))
    if args.new_only:
        results = [j for j in results if j["is_new"]]
    results.sort(key=lambda j: (not j["is_new"], j["company"].lower(), j["title"]))

    csv_path, html_path = HERE / f"jobs-{name}.csv", HERE / f"jobs-{name}.html"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["company", "title", "location", "exp", "url", "source", "is_new"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    def exp_cell(j):
        return f"{j['exp']}+ yrs" if j.get("exp") is not None else "?"

    rows = "\n".join(
        f"<tr><td>{htmllib.escape(j['company'])}</td><td>{htmllib.escape(j['title'])}</td>"
        f"<td>{htmllib.escape(j['location'])}</td><td>{exp_cell(j)}</td>"
        f"<td><a href='{htmllib.escape(j['url'])}' target='_blank'>Apply</a></td>"
        f"<td><b>{'NEW' if j['is_new'] else ''}</b></td></tr>" for j in results)
    html_path.write_text(
        f"<meta charset='utf-8'><title>Openings for {htmllib.escape(name)}</title>"
        "<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse}"
        "td,th{border-bottom:1px solid #ddd;padding:6px 12px;text-align:left}input{padding:6px;width:320px}</style>"
        f"<h2>{len(results)} openings for {htmllib.escape(name)} - {datetime.now():%d %b %Y %H:%M}</h2>"
        "<input id=q placeholder='filter: city, company, keyword...' oninput='f()'>"
        "<table><thead><tr><th>Company</th><th>Title</th><th>Location</th><th>Exp asked</th><th></th><th></th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<script>function f(){var q=document.getElementById('q').value.toLowerCase();"
        "document.querySelectorAll('tbody tr').forEach(function(r){"
        "r.style.display=r.innerText.toLowerCase().indexOf(q)>-1?'':'none'})}</script>",
        encoding="utf-8")

    print(f"{len(entries)} boards checked ({len(failed)} failed). {before} title/location matches, "
          f"{dropped} dropped by experience filter, {len(results)} shown.")
    print(f"Wrote {csv_path.name} and {html_path.name}\n")
    print("Per board (fetched -> matched):")
    for n, ats, fetched, matched in sorted(boards, key=lambda b: (-b[3], b[0].lower())):
        print(f"  {n} [{ats}]: {fetched} -> {matched}")
    if failed:
        print("\nFailed boards (fix or remove from companies.json):")
        for n, ats, err in sorted(failed):
            print(f"  {n} [{ats}]: {err}")
