#!/usr/bin/env python3
"""Job crawler for Shakshi: Senior Software Engineer (backend / distributed systems / data pipelines), 6+ years, India."""
from jobcrawler import main

PROFILE = {
    "name": "shakshi",
    "query": "senior software engineer",     # used by Amazon / Workday / Microsoft searches
    "search_term": "senior",                  # used by SmartRecruiters

    # Senior-level markers: Senior / Sr, SDE-3 / Engineer III, SMTS (Salesforce-style), MTS-3, tech lead
    "level": (r"\b(senior|sr\.?|smts|sde[\s-]*(iii|3)|swe[\s-]*(iii|3)|"
              r"software (development |dev )?engineer[\s-]*(iii|3)|engineer[\s-]*(iii|3)|"
              r"(mts|member of technical staff)[\s-]*(3|iii)|tech lead|technical lead|"
              r"lead (software|backend|back-end) engineer)\b"),

    # Titles containing any of these are dropped. Remove 'staff|principal' if you also want
    # Staff-level roles (usually 8+ years); remove 'security' / 'machine learning' etc. to widen.
    "exclude": (r"\b((?<!technical )staff|principal|distinguished|fellow|architect|android|ios|mobile|front[\s-]?end|ui|"
                r"machine learning|ml|data scientist|applied scientist|security|network|salesforce|sap|"
                r"netsuite|crm|dynamics|power platform|rpa|hardware|mechanical|electrical|firmware|"
                r"embedded|asic|vlsi|forward deployed|it automation|release|support|intern|trainee)\b"),

    # Years the posting asks for. A 6-year engineer fits postings asking 5-10 years.
    # Unreadable ones are kept and shown with '?'. Change exp_min to 6 if you want only 6+ postings.
    "exp_min": 5,
    "exp_max": 10,
}

if __name__ == "__main__":
    main(PROFILE)
