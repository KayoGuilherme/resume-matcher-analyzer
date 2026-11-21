"""ATS keyword coverage: which of the job's keywords appear literally in the resume text.

An applicant tracking system scans for the words themselves, so this is a literal search (with
the known aliases) and no short name is treated as ambiguous. Only the resume counts.
"""

from collections.abc import Sequence

from app.ai.matching.models import AtsCoverage, FoundKeyword
from app.ai.matching.text import SearchableText, ats_forms


def ats_coverage(ats_keywords: Sequence[str], resume: SearchableText) -> AtsCoverage:
    found: list[FoundKeyword] = []
    missing: list[str] = []
    for keyword in ats_keywords:
        matches = resume.find(ats_forms(keyword))
        if matches:
            found.append(FoundKeyword(keyword=keyword, matched_text=matches[0].text))
        else:
            missing.append(keyword)
    return AtsCoverage(found=found, missing=missing)
