"""Mandatory wording (spec Sections 1, 2, 6, 7). Single source of truth.

UI, report and certificate must import from here so the text never drifts.
"""

POSITIONING = (
    "A free pre-check that catches open-web and paraphrased plagiarism so you can "
    "fix issues before your institution's official check."
)

REPORT_DISCLAIMER = (
    "This report indicates textual similarity with sources in the searched database. "
    "It is an indicator, not proof of plagiarism. Properly quoted and cited material "
    "may appear as a match. The database does not include all published or paywalled "
    "work, so this result does not guarantee that a document is free of plagiarism. "
    "A qualified human must make the final judgment under the institution's policy."
)

CERTIFICATE_DISCLAIMER = (
    "This certificate is an automated indicator only. It is not issued by any "
    "accredited body, does not constitute proof of plagiarism or academic "
    "misconduct, and does not guarantee originality. Human review is required "
    "for any official decision."
)

INSTITUTION_NOTE = "Some institutions accept only approved tools; check your institution's policy."

COVERAGE_NOTE = (
    "Free tools cover fewer sources than paid tools. Expect lower similarity than "
    "Turnitin/iThenticate on real theses."
)

# Phrases that must never appear in any user-facing output (checked in tests).
FORBIDDEN_PHRASES = (
    "100% original",
    "plagiarism free",
    "plagiarism-free",
    "guilty",
    "passed",
    "failed",
    "replaces turnitin",
)
