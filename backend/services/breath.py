"""
Breath scripting for cloud voices.

Plain text read by a cloned voice sounds like a list: every sentence
starts on a fresh contour and dies on a full stop. A human guide
breathes — audibly — and holds silence between ideas. This module turns
plain text into a *prosody script*: the same words, annotated with
MiniMax sound tags (``(inhale)``, ``(exhale)``, ``(breath)``, ``(sighs)``)
and native pause markers (``<#x#>``), so the engine performs the breath
instead of merely reading the instruction to breathe.

The annotation is deterministic and text-driven:

* Sentences and clauses get silence sized by the chosen style.
* A clause that *describes* a breath ("inhala despacio", "exhala por la
  boca") gets the matching audible breath attached to it.
* A clause that names its own duration ("inhala en 4 segundos", "retén
  2 segundos") holds that many seconds of real silence.
* Markup already present in the text is authored intent: it is preserved
  and never duplicated.

Everything emitted here is valid MiniMax markup. ``sanitize`` enforces
the three rules the API rejects — durations outside [0.01, 99.99],
consecutive markers, and markers at the very start or end of the text —
which is also why the engine used to read stray markers aloud.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ── MiniMax markup primitives ─────────────────────────────────────────

MIN_PAUSE_SECONDS = 0.01
MAX_PAUSE_SECONDS = 99.99

# Pauses inferred from the text ("retén 5 segundos") are capped well below
# the API maximum: these clips are notifications, not a whole session.
MAX_INFERRED_PAUSE_SECONDS = 8.0

PAUSE_MARKER_RE = re.compile(r"<#(\d+(?:\.\d+)?)#>")

# Interjections accepted by speech-2.8-hd / speech-2.8-turbo. Older model
# families read them aloud, so they are stripped rather than sent.
SOUND_TAGS = frozenset(
    {
        "laughs", "chuckle", "coughs", "clear-throat", "groans", "breath",
        "pant", "inhale", "exhale", "gasps", "sniffs", "sighs", "snorts",
        "burps", "lip-smacking", "humming", "hissing", "emm", "sneezes",
    }
)

SOUND_TAG_RE = re.compile(
    r"\((" + "|".join(re.escape(t) for t in sorted(SOUND_TAGS)) + r")\)",
    re.IGNORECASE,
)


# ── Styles ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BreathStyle:
    """How much air and silence a given register wants."""

    name: str
    sentence_pause: float  # silence between sentences
    clause_pause: float  # silence at internal clause boundaries
    cue_pause: float  # silence held after an audible breath
    lead_in: Optional[str]  # tag opening the script, or None
    min_clause_chars: int  # clauses shorter than this get no pause
    cue_breaths: bool  # turn described breaths into performed ones


BREATH_STYLES: dict[str, BreathStyle] = {
    # Pass-through: only sanitizes markup the author wrote by hand.
    "off": BreathStyle("off", 0.0, 0.0, 0.0, None, 0, False),
    # "YO SOY ..." lines: each statement lands, then room to absorb it.
    # Short clause pauses keep the cadence steady rather than solemn.
    "affirmation": BreathStyle("affirmation", 0.9, 0.3, 0.7, None, 18, True),
    # Guided practice: long holds, and the guide breathes with the listener.
    "meditation": BreathStyle("meditation", 1.8, 0.6, 1.2, "(breath)", 16, True),
    # Spoken-word delivery: continuous arc, breath only where described.
    "narration": BreathStyle("narration", 0.4, 0.0, 0.5, None, 0, True),
}

DEFAULT_STYLE = "off"


# ── Cue detection ─────────────────────────────────────────────────────

# Ordered: the first match wins, so "exhala" beats the generic "respira".
_CUE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    (
        "(inhale)",
        re.compile(
            r"\b(?:inhala\w*|inspira\w*|toma\s+(?:aire|un?\s+respiro)|coge\s+aire|"
            r"llena\s+(?:los|tus)\s+pulmones|inhale\w*|breathe\s+in|breathing\s+in)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "(exhale)",
        re.compile(
            r"\b(?:exhala\w*|expira\w*|suelta\s+(?:el|todo\s+el)\s+aire|"
            r"saca\s+el\s+aire|vac[íi]a\s+(?:los|tus)\s+pulmones|exhale\w*|"
            r"breathe\s+out|breathing\s+out)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "(sighs)",
        re.compile(r"\b(?:suspir\w*|sigh\w*)\b", re.IGNORECASE),
    ),
    (
        "(breath)",
        re.compile(r"\b(?:respira\w*|respiraci[óo]n\w*|breathe\w*|breath)\b", re.IGNORECASE),
    ),
)

# "retén 2 segundos", "sostén la respiración", "hold for three counts"
_HOLD_RE = re.compile(
    r"\b(?:ret[ée]n\w*|sost[ée]n\w*|mant[ée]n\w*|aguanta\w*|hold(?:ing)?)\b",
    re.IGNORECASE,
)

# An explicit count the clause asks the listener to keep.
_SECONDS_RE = re.compile(
    r"\b(\d{1,2})\s*(?:segundos?|seg\b|s\b|counts?|seconds?)", re.IGNORECASE
)

_SPELLED_NUMBERS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8,
}

_SPELLED_SECONDS_RE = re.compile(
    r"\b(" + "|".join(_SPELLED_NUMBERS) + r")\s*(?:segundos?|counts?|seconds?)",
    re.IGNORECASE,
)

# Sentence terminators, and the abbreviations that only look like one.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_ABBREV_TAIL_RE = re.compile(
    r"\b(?:sr|sra|srta|dr|dra|prof|etc|ej|p\.?\s*ej|mr|mrs|ms|vs|a\.?\s*m|p\.?\s*m)\.$",
    re.IGNORECASE,
)

# Clause boundaries worth breathing at. Commas inside numbers stay put.
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,;:])(?!\d)\s+|(?<=—)\s*")

# A breathing instruction usually chains its steps with a conjunction
# rather than a comma ("reten dos segundos y exhala"). Splitting there too
# lets each step keep its own breath, but only inside a clause that really
# describes several — elsewhere it would chop ordinary prose.
_STEP_SPLIT_RE = re.compile(
    r"\s+(?=(?:y|e|luego|despu[\u00e9e]s|entonces|then|and)\s+)", re.IGNORECASE
)


# ── Public helpers ────────────────────────────────────────────────────


def has_markup(text: str) -> bool:
    """True when *text* already carries pause markers or sound tags."""
    return bool(PAUSE_MARKER_RE.search(text) or SOUND_TAG_RE.search(text))


def strip_markup(text: str, *, pauses: bool = True, tags: bool = True) -> str:
    """Remove MiniMax markup — for engines that would read it aloud."""
    if tags:
        text = SOUND_TAG_RE.sub(" ", text)
    if pauses:
        text = PAUSE_MARKER_RE.sub(" ", text)
    return _collapse_spaces(text)


def sanitize(text: str) -> str:
    """Make every pause marker in *text* legal for the MiniMax API.

    Durations are clamped and rounded to two decimals, runs of adjacent
    markers are merged into a single pause carrying their total, and
    markers at the very start or end are dropped — the API rejects all
    three, and a rejected marker is what gets spoken out loud.
    """
    text = _RUN_RE.sub(_merge_run, text)
    text = _LEADING_RUN_RE.sub("", text)
    text = _TRAILING_RUN_RE.sub("", text)
    return _collapse_spaces(text)


def annotate(text: str, style: str = DEFAULT_STYLE, *, sound_tags: bool = True) -> str:
    """Return *text* as a prosody script in the given breath *style*.

    Args:
        text: Plain text, or text the author already annotated by hand.
        style: A key of :data:`BREATH_STYLES`. Unknown names fall back to
            ``"off"`` so a bad value degrades to plain speech, never to a
            mangled script.
        sound_tags: False when the target model cannot perform tags
            (anything below speech-2.8) — silence still gets scripted.
    """
    resolved = BREATH_STYLES.get(style or DEFAULT_STYLE, BREATH_STYLES["off"])
    text = text.strip()
    if not text:
        return ""
    if resolved.name == "off":
        out = text if sound_tags else strip_markup(text, pauses=False)
        return sanitize(out)

    pieces: list[str] = []
    sentences = _split_sentences(text)
    for i, sentence in enumerate(sentences):
        pieces.append(_annotate_sentence(sentence, resolved, sound_tags))
        if i < len(sentences) - 1 and resolved.sentence_pause > 0:
            pieces.append(_marker(resolved.sentence_pause))

    script = " ".join(p for p in pieces if p)

    if sound_tags and resolved.lead_in and not script.lstrip().startswith("("):
        script = f"{resolved.lead_in} {script}"
    elif not sound_tags:
        script = strip_markup(script, pauses=False)

    return sanitize(script)


# ── Internals ─────────────────────────────────────────────────────────

_RUN_RE = re.compile(r"(?:\s*<#(?:\d+(?:\.\d+)?)#>\s*)+")
_LEADING_RUN_RE = re.compile(r"^(?:\s*<#(?:\d+(?:\.\d+)?)#>\s*)+")
_TRAILING_RUN_RE = re.compile(r"(?:\s*<#(?:\d+(?:\.\d+)?)#>\s*)+$")


def _merge_run(match: re.Match) -> str:
    total = sum(float(v) for v in PAUSE_MARKER_RE.findall(match.group(0)))
    return _marker(total) + " "


def _marker(seconds: float) -> str:
    clamped = max(MIN_PAUSE_SECONDS, min(MAX_PAUSE_SECONDS, float(seconds)))
    return f"<#{clamped:.2f}#>"


def _collapse_spaces(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _split_sentences(text: str) -> list[str]:
    """Split on sentence terminators, rejoining false positives."""
    parts = _SENTENCE_SPLIT_RE.split(text)
    merged: list[str] = []
    for part in parts:
        if merged and _ABBREV_TAIL_RE.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return [p.strip() for p in merged if p.strip()]


def _annotate_sentence(sentence: str, style: BreathStyle, sound_tags: bool) -> str:
    # Hand-written markup is authored intent — leave the sentence alone.
    if has_markup(sentence):
        return sentence

    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(sentence) if c.strip()]
    if style.cue_breaths:
        clauses = [step for clause in clauses for step in _split_steps(clause)]
    if not clauses:
        return sentence

    out: list[str] = []
    for i, clause in enumerate(clauses):
        out.append(clause)
        is_last = i == len(clauses) - 1

        cue = _cue_for(clause) if style.cue_breaths else None
        if cue is not None:
            tag, hold = cue
            if tag and sound_tags:
                out.append(tag)
            pause = hold if hold is not None else style.cue_pause
            if pause > 0 and not (is_last and tag is None):
                out.append(_marker(pause))
            continue

        if is_last or style.clause_pause <= 0:
            continue
        if len(clause) >= style.min_clause_chars:
            out.append(_marker(style.clause_pause))

    return " ".join(out)


def _split_steps(clause: str) -> list[str]:
    """Break a breathing instruction so each step keeps its own breath.

    "Exhala todo el aire y siente el cuerpo aflojarse" is one clause but
    two moments: the tag belongs to the first, otherwise the voice exhales
    after describing the release instead of during it.
    """
    if not _count_cues(clause):
        return [clause]
    steps = [part.strip() for part in _STEP_SPLIT_RE.split(clause) if part.strip()]
    return steps or [clause]


def _count_cues(clause: str) -> int:
    hits = sum(1 for _, pattern in _CUE_PATTERNS if pattern.search(clause))
    if _HOLD_RE.search(clause):
        hits += 1
    return hits



def _cue_for(clause: str) -> Optional[tuple[Optional[str], Optional[float]]]:
    """Map a clause onto (sound tag, explicit hold) or None.

    A hold cue ("retén dos segundos") is silence with no tag: the guide
    stops talking while the listener keeps the air in.
    """
    seconds = _explicit_seconds(clause)

    for tag, pattern in _CUE_PATTERNS:
        if pattern.search(clause):
            return tag, seconds

    if _HOLD_RE.search(clause):
        # A bare "mantén la postura" is not a breath hold — only honour
        # the cue when the clause says for how long.
        return (None, seconds) if seconds is not None else None

    return None


def _explicit_seconds(clause: str) -> Optional[float]:
    match = _SECONDS_RE.search(clause)
    if match:
        value = float(match.group(1))
    else:
        spelled = _SPELLED_SECONDS_RE.search(clause)
        if not spelled:
            return None
        value = float(_SPELLED_NUMBERS[spelled.group(1).lower()])
    return min(value, MAX_INFERRED_PAUSE_SECONDS)
