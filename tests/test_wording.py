import re

from app import wording


def test_mandatory_wording_present():
    assert "pre-check" in wording.POSITIONING
    assert "indicator, not proof" in wording.REPORT_DISCLAIMER
    assert "not issued by any accredited body" in wording.CERTIFICATE_DISCLAIMER


def test_no_forbidden_claims_in_user_facing_text():
    texts = [
        wording.POSITIONING,
        wording.REPORT_DISCLAIMER,
        wording.CERTIFICATE_DISCLAIMER,
        wording.INSTITUTION_NOTE,
        wording.COVERAGE_NOTE,
    ]
    for t in texts:
        for bad in wording.FORBIDDEN_PHRASES:
            # whole-word match so "not guarantee ... free of plagiarism" is fine
            assert not re.search(rf"\b{re.escape(bad)}\b", t, re.IGNORECASE), (bad, t)
