#!/usr/bin/env python3
"""Job crawler for Mahi: SDE-2 backend roles (Java, distributed systems; AI/agent roles welcome too), 3+ years, India."""
from jobcrawler import main

PROFILE = {
    "name": "mahi",
    "query": "software engineer",
    "search_term": "engineer",

    # SDE-2 only: "SDE II", "SDE-2", "Software (Development) Engineer II/2", "Engineer II", "MTS 2", ...
    # (Want 'Senior' titles too? Add  senior|sr\.?|  right after the opening  \b(  below.)
    "level": (r"\b(sde[\s-]*(ii|2)|swe[\s-]*(ii|2)|"
              r"software (development |dev )?engineer[\s-]*(ii|2)|"
              r"engineer[\s-]*(ii|2)|developer[\s-]*(ii|2)|"
              r"(mts|member of technical staff)[\s-]*(2|ii))\b"),

    # Plain titles like "Software Engineer, Backend" carry no level. Keep them ONLY when the job
    # description says 3-7 years of experience (so they are really SDE-2 level).
    "generic": True,
    "generic_role": (r"\b(software|backend|back-end|developer|sde|swe|java|distributed|platform|"
                     r"member of technical staff|mts)\b"),

    # Also let AI-agent / LLM titles through (her CV has a production LangGraph agent), but not only those
    "role_extra": r"|\bai\b|agent|agents|llm|genai|generative",

    "exclude": (r"\b((?<!technical )staff|principal|distinguished|fellow|architect|android|ios|mobile|front[\s-]?end|ui|"
                r"data scientist|applied scientist|network|hardware|mechanical|electrical|firmware|"
                r"embedded|asic|vlsi|forward deployed|it automation|release|support|consultant|"
                r"salesforce|netsuite|crm|dynamics|power platform|rpa|intern|trainee)\b"),

    # 3 to 7 years asked. SmartRecruiters / Workday feeds have no description, so those show '?'
    "exp_min": 3,
    "exp_max": 7,
}

if __name__ == "__main__":
    main(PROFILE)
