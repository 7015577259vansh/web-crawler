#!/usr/bin/env python3
"""Job crawler for Vansh: software / AI internships and fresher / new-grad roles (B.E. 2023-2027), India."""
from jobcrawler import main

PROFILE = {
    "name": "vansh",
    "query": "software engineer intern",
    "search_term": "intern",

    # Entry-level markers: interns, new grads, trainees, freshers, SDE-1 / Engineer I
    "level": (r"\b(intern|interns|internship|trainee|new[\s-]?grad|new college|college grad|graduate|"
              r"entry[\s-]?level|campus|university|early (career|talent)|fresher|freshers|junior|jr\.?|"
              r"apprentice|co-?op|student|"
              r"associate (software|engineer|developer)|"
              r"sde[\s-]*(1|i)|software (development |dev )?engineer[\s-]*(1|i)|engineer[\s-]*(1|i)|swe[\s-]*(1|i))\b"),

    # Any engineering/software title that is also entry-level, plus AI / ML / data / web.
    # (VLSI words removed: you asked for software and AI. To bring VLSI back, append
    #  |vlsi|rtl|asic|verification|embedded|firmware|physical design|digital design|analog  below.)
    "role_extra": (r"|engineer|engineering|research|data|\bai\b|\bml\b|llm|genai|react|web|frontend|"
                   r"front[\s-]?end|full[\s-]?stack|prompt|nlp|computer vision|deep learning|python|"
                   r"analytics|automation|mobile|android|ios"),

    # Untitled-level roles ("Software Engineer") are kept only if the description says 0-1 years
    # or mentions freshers / new grads / entry level
    "generic": True,
    "generic_role": (r"\b(software|developer|sde|swe|backend|back-end|full[\s-]?stack|front[\s-]?end|"
                     r"python|java|ai|ml|machine learning|data engineer)\b"),
    "generic_text": r"\b(freshers?|new grad(uate)?s?|recent graduates?|entry[\s-]level|no (prior )?experience)\b",

    "exclude": (r"\b(senior|sr\.?|(?<!technical )staff|principal|lead|architect|ii|iii|iv|2|3|manager|director|"
                r"mechanical|civil|chemical|electrical|electronics?|hardware|manufacturing|production|"
                r"hr|human resources|finance|accounts?|legal|operations|business|marketing|content|"
                r"data entry)\b"),

    # Entry-level: drop postings that explicitly ask for more than 1 year
    "exp_min": None,
    "exp_max": 1,
}

if __name__ == "__main__":
    main(PROFILE)
