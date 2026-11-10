"""Document exclusions and citation verification module.

Excludes bibliography/references and properly quoted+cited passages from the similarity score,
while flagging quoted-uncited passages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Citation patterns:
# 1. Parenthetical year: (Smith, 2020), (Doe et al., 2019, p. 12), (Johnson 2018)
# 2. Numbered citation: [1], [2, 3], [4-7], [12, 15-18]
CITATION_PATTERN = re.compile(
    r"\((?:[A-Za-z\s.,]+(?:et\s+al\.?)?,?\s*)?(?:19|20)\d{2}(?:\s*,\s*p(?:p)?\.\s*\d+(?:-\d+)?)?\)|\[\s*\d+(?:\s*[,;\-–]\s*\d+)*\s*\]"
)

# Reference section header regex
REF_HEADER_PATTERN = re.compile(
    r"^\s*(?:references|bibliography|works\s+cited|reference\s+list|literature\s+cited)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Acknowledgements & Dedication header regex
ACK_HEADER_PATTERN = re.compile(
    r"^\s*(?:acknowledgements?|acknowledgments?|dedication)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Next section header to mark end of acknowledgements
SECTION_BREAK_PATTERN = re.compile(
    r"^\s*(?:abstract|table of contents|contents|introduction|chapter\s+1|1\.\s+introduction)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Title page / Institutional cover markers
TITLE_PAGE_MARKERS = [
    re.compile(r"submitted\s+in\s+partial\s+fulfillment\s+of\s+(?:the\s+)?requirements", re.IGNORECASE),
    re.compile(r"(?:thesis|dissertation)\s+submitted\s+to", re.IGNORECASE),
    re.compile(r"(?:supervised|advised)\s+by\s*:", re.IGNORECASE),
    re.compile(r"department\s+of\s+.+faculty\s+of", re.IGNORECASE),
    re.compile(r"all\s+rights\s+reserved\s*[.,]?\s*(?:copyright|\(c\)|©)?", re.IGNORECASE),
]

# Quotation regex: captures passages enclosed in standard or smart quotes of reasonable length (>= 30 chars)
QUOTED_TEXT_PATTERN = re.compile(r'["“]([^"”]{30,1000}?)["”]', re.DOTALL)

# Common academic boilerplate n-grams (normalized words tuple)
COMMON_ACADEMIC_BOILERPLATE = frozenset([
    ("in", "order", "to", "investigate"),
    ("the", "remainder", "of", "this", "paper"),
    ("remainder", "of", "this", "paper", "is"),
    ("of", "this", "paper", "is", "organized"),
    ("this", "paper", "is", "organized", "as"),
    ("paper", "is", "organized", "as", "follows"),
    ("of", "this", "paper", "is", "structured"),
    ("this", "paper", "is", "structured", "as"),
    ("paper", "is", "structured", "as", "follows"),
    ("as", "shown", "in", "figure"),
    ("as", "can", "be", "seen", "in"),
    ("can", "be", "seen", "in", "figure"),
    ("the", "results", "are", "shown", "in"),
    ("results", "are", "shown", "in", "table"),
    ("to", "the", "best", "of", "our"),
    ("the", "best", "of", "our", "knowledge"),
    ("further", "research", "is", "needed", "to"),
    ("for", "the", "purposes", "of", "this"),
    ("the", "purposes", "of", "this", "study"),
    ("it", "is", "important", "to", "note"),
    ("is", "important", "to", "note", "that"),
    ("has", "attracted", "significant", "attention", "in"),
    ("play", "an", "important", "role", "in"),
    ("plays", "an", "important", "role", "in"),
    ("in", "accordance", "with", "the"),
    ("submitted", "in", "partial", "fulfillment", "of"),
    ("in", "partial", "fulfillment", "of", "the"),
    ("partial", "fulfillment", "of", "the", "requirements"),
    ("a", "statistically", "significant", "difference", "was"),
])


@dataclass(frozen=True)
class ExclusionSpan:
    start: int
    end: int
    reason: str


@dataclass
class ExclusionReport:
    spans: list[ExclusionSpan] = field(default_factory=list)
    quoted_uncited_count: int = 0
    flags: list[str] = field(default_factory=list)

    def is_excluded(self, char_offset: int) -> bool:
        """Check whether a specific character offset falls inside an excluded span."""
        for s in self.spans:
            if s.start <= char_offset < s.end:
                return True
        return False


def is_boilerplate(shingle: tuple[str, ...]) -> bool:
    """Return True if a shingle matches known academic boilerplate phrases."""
    return shingle in COMMON_ACADEMIC_BOILERPLATE or (
        len(shingle) >= 4 and shingle[:4] in COMMON_ACADEMIC_BOILERPLATE
    )


def find_exclusions(text: str) -> ExclusionReport:
    """Analyze document text to identify excluded zones and citation flags."""
    spans: list[ExclusionSpan] = []
    flags: list[str] = []

    text_len = len(text)
    if not text or text_len < 50:
        return ExclusionReport(spans=[], quoted_uncited_count=0, flags=[])

    # 1. Title Page / Institutional Cover Exclusion (checks first 1500 chars)
    header_window = text[:min(1500, text_len)]
    for marker in TITLE_PAGE_MARKERS:
        m = marker.search(header_window)
        if m:
            # Exclude up to double newline or 600 chars from document start
            end_pos = min(600, text_len)
            newline_break = text.find("\n\n\n", m.start())
            if 0 < newline_break <= 1200:
                end_pos = newline_break
            spans.append(
                ExclusionSpan(start=0, end=end_pos, reason="title_page_preamble")
            )
            flags.append("Title/cover page institutional preamble excluded from similarity calculation")
            break

    # 2. Acknowledgements / Dedication Section Exclusion
    ack_match = ACK_HEADER_PATTERN.search(text)
    if ack_match and ack_match.start() < text_len * 0.40:
        ack_start = ack_match.start()
        # Find next section break
        next_sec = SECTION_BREAK_PATTERN.search(text, ack_start + 20)
        ack_end = next_sec.start() if next_sec else min(ack_start + 1200, text_len)
        spans.append(
            ExclusionSpan(start=ack_start, end=ack_end, reason="acknowledgements_section")
        )
        flags.append("Acknowledgements/Dedication section excluded from scoring")

    # 3. Bibliography / References section detection (must appear in latter 60% of document)
    ref_matches = list(REF_HEADER_PATTERN.finditer(text))
    valid_ref_headers = [m for m in ref_matches if m.start() >= text_len * 0.40]

    if valid_ref_headers:
        # Use the latest valid reference header to avoid early table-of-contents false positives
        chosen_header = valid_ref_headers[-1]
        spans.append(
            ExclusionSpan(
                start=chosen_header.start(),
                end=text_len,
                reason="references_section",
            )
        )
        flags.append(
            f"References/Bibliography section detected starting at character {chosen_header.start()} and excluded from scoring"
        )

    # 2. Quotation analysis with citation check
    quoted_uncited_count = 0
    ref_start = spans[0].start if spans else text_len

    for m in QUOTED_TEXT_PATTERN.finditer(text):
        q_start, q_end = m.start(), m.end()
        # If quote is inside the already excluded references section, skip
        if q_start >= ref_start:
            continue

        # Look for citation directly within the quote or up to 80 chars after the closing quote
        window_after = text[q_end: min(q_end + 80, text_len)]
        quote_body = m.group(1)

        has_citation = bool(
            CITATION_PATTERN.search(window_after) or CITATION_PATTERN.search(quote_body[-40:])
        )

        if has_citation:
            spans.append(
                ExclusionSpan(
                    start=q_start,
                    end=q_end,
                    reason="quoted_and_cited",
                )
            )
        else:
            quoted_uncited_count += 1

    if quoted_uncited_count > 0:
        flags.append(
            f"{quoted_uncited_count} quoted passage(s) lacked nearby formal citations and were included in scoring"
        )

    # Sort spans by start offset
    spans.sort(key=lambda s: s.start)

    return ExclusionReport(
        spans=spans,
        quoted_uncited_count=quoted_uncited_count,
        flags=flags,
    )
