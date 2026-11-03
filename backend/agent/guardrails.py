"""Guardrails around the inspection agent.

Four checks, each cheap and deterministic so they can be unit-tested:

1. Question check   - length limits before anything reaches the model.
2. Injection filter - retrieved passages and database text are data, not
                      instructions. Sentences that try to give the model orders
                      are removed before the model sees them. The phrase list
                      follows the keyword filter from my RAG poisoning study,
                      where it blocked the tested injection templates.
3. Tool budget      - a hard cap on tool calls per question (enforced in loop.py).
4. Grounding check  - every number in the final answer should appear in some
                      tool result. Numbers that don't are reported, not hidden.
"""

import json
import re

MAX_QUESTION_CHARS = 500
MIN_QUESTION_CHARS = 3
MAX_TOOL_CALLS = 6

INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|messages)",
    r"disregard (all |any )?(the )?(previous|prior|above|earlier|your) (instructions|rules)",
    r"forget (all |any )?(your|the|previous) (instructions|rules)",
    r"you are now\b",
    r"new instructions?:",
    r"system prompt",
    r"\bact as (a|an|the)\b",
    r"reveal (your|the) (instructions|prompt|rules)",
    r"(call|use|invoke) the \w+ tool",
    r"<\s*/?\s*(script|system|instructions?)\s*>",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


class QuestionRejected(ValueError):
    pass


def check_question(question) -> str:
    if not isinstance(question, str):
        raise QuestionRejected("Question must be text.")
    question = " ".join(question.split())
    if len(question) < MIN_QUESTION_CHARS:
        raise QuestionRejected("Question is too short.")
    if len(question) > MAX_QUESTION_CHARS:
        raise QuestionRejected(f"Keep questions under {MAX_QUESTION_CHARS} characters.")
    return question


def strip_injections(text: str) -> tuple[str, int]:
    """Remove sentences that look like instructions. Returns (clean, removed)."""
    if not text or not _INJECTION.search(text):
        return text, 0
    kept, removed = [], 0
    for sentence in _SENTENCE_SPLIT.split(text):
        if _INJECTION.search(sentence):
            removed += 1
        elif sentence.strip():
            kept.append(sentence.strip())
    return " ".join(kept), removed


def sanitize(value) -> tuple[object, int]:
    """Apply strip_injections to every string inside a tool result."""
    if isinstance(value, str):
        return strip_injections(value)
    if isinstance(value, list):
        out, total = [], 0
        for item in value:
            clean, n = sanitize(item)
            out.append(clean)
            total += n
        return out, total
    if isinstance(value, dict):
        out, total = {}, 0
        for key, item in value.items():
            clean, n = sanitize(item)
            out[key] = clean
            total += n
        return out, total
    return value, 0


_NUMBER = re.compile(r"(?<![\w§.-])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w-])")


def _numbers(text: str) -> list[str]:
    found = []
    for match in _NUMBER.finditer(text):
        whole = match.group(1).replace(",", "")
        frac = match.group(2)
        found.append(f"{whole}.{frac}" if frac else whole)
    return found


def _variants(value: float) -> set[str]:
    """Ways a number from a tool result could be written in an answer."""
    out = {repr(value), str(value)}
    for digits in (0, 1, 2):
        rounded = round(value, digits)
        out.add(f"{rounded:.{digits}f}")
    if float(value).is_integer():
        out.add(str(int(value)))
    return out


def unverified_numbers(answer: str, tool_results: list, question: str = "") -> list[str]:
    """Numbers in the answer that neither a tool result nor the question supports.

    Small integers (0-31), years and Chicago ZIP codes are ignored: they are
    list positions, day numbers, or identifiers rather than measured values.
    """
    supported = set()
    blob = json.dumps(tool_results, default=str) + " " + question
    # Source text often glues units to numbers ("57C (135F)", "41F"), so read
    # every digit run there. Answers are still parsed strictly.
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?", blob):
        token = token.replace(",", "")
        try:
            supported |= _variants(float(token))
        except ValueError:
            continue
    flagged = []
    for token in _numbers(answer):
        number = float(token)
        if number.is_integer() and (number <= 31 or 1990 <= number <= 2100
                                    or re.fullmatch(r"60[6-8]\d\d", token)):
            continue
        candidates = {token, token.rstrip("0").rstrip(".") if "." in token else token}
        if not candidates & supported:
            flagged.append(token)
    return flagged
