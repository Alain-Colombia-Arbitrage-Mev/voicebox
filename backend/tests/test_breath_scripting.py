"""Tests for breath scripting and the MiniMax markup it produces.

Two things are being pinned here. First, that a described breath becomes a
performed one — the point of the feature. Second, that every script is legal
MiniMax markup: the API rejects markers that are out of range, consecutive,
or sitting at either end of the text, and a rejected marker gets read out
loud in the middle of a meditation.
"""

import pytest

from backend.services.breath import (
    MAX_INFERRED_PAUSE_SECONDS,
    PAUSE_MARKER_RE,
    annotate,
    has_markup,
    sanitize,
    strip_markup,
)

# Verbatim lines from the mirror-hours library this was built for.
MICRO_GESTURES = [
    "Cierra los ojos, exhala todo el aire largo por la boca y siente cómo tu cuerpo se afloja.",
    "Apoya suavemente tu mano derecha sobre el pecho y siente el calor reconfortante de tu propia palma.",
    "Separa los dientes, suelta la lengua del paladar y deja caer el peso de la cabeza en la almohada.",
    "Inhala despacio en 4 segundos, retén 2 segundos y exhala con un suave suspiro de alivio.",
]

AFFIRMATIONS = [
    "YO SOY paz profunda. Dejo ir el día 1 con amor y me entrego a un descanso sagrado y reparador.",
    "YO SOY mi propio refugio. Mi cuerpo sabe cómo sanar y renovar cada célula en el silencio de la noche.",
]


# ── described breath → performed breath ──────────────────────────────


def test_inhale_cue_becomes_an_audible_inhale():
    out = annotate("Inhala despacio y suelta.", "meditation")
    assert "(inhale)" in out


def test_exhale_cue_lands_on_its_own_clause_not_the_sentence_end():
    out = annotate(MICRO_GESTURES[0], "meditation")
    # The breath belongs to "exhala todo el aire", not to the sentence's
    # final words about the body softening.
    assert out.index("(exhale)") < out.index("siente cómo tu cuerpo")


def test_explicit_count_becomes_real_silence():
    out = annotate("Inhala despacio en 4 segundos y suelta.", "meditation")
    assert "(inhale)<#4.00#>" in out


def test_spelled_out_count_is_honoured():
    out = annotate("Toma aire tres segundos y suéltalo.", "meditation")
    assert "(inhale)<#3.00#>" in out


def test_inferred_pause_is_capped():
    out = annotate("Retén 30 segundos y suelta.", "meditation")
    pauses = [float(v) for v in PAUSE_MARKER_RE.findall(out)]
    assert pauses and max(pauses) <= MAX_INFERRED_PAUSE_SECONDS


def test_multi_step_instruction_keeps_one_breath_per_step():
    out = annotate(MICRO_GESTURES[3], "meditation")
    assert out.index("(inhale)") < out.index("(exhale)")
    assert "<#4.00#>" in out  # the named inhale
    assert "<#2.00#>" in out  # the named hold


def test_hold_without_a_duration_is_not_a_breath():
    # "Mantén la postura" is posture, not breath: nothing to hold silence for.
    assert annotate("Mantén la postura firme.", "meditation").count("<#") == 0


def test_text_without_cues_gets_silence_but_no_breaths():
    out = annotate(MICRO_GESTURES[1], "meditation")
    assert "(inhale)" not in out and "(exhale)" not in out


# ── styles ───────────────────────────────────────────────────────────


def test_off_style_leaves_words_alone():
    assert annotate(AFFIRMATIONS[0], "off") == AFFIRMATIONS[0]


def test_unknown_style_degrades_to_off():
    assert annotate(AFFIRMATIONS[0], "nonsense") == AFFIRMATIONS[0]


def test_affirmation_pauses_between_statements():
    out = annotate(AFFIRMATIONS[0], "affirmation")
    assert "YO SOY paz profunda.<#0.90#>" in out


def test_meditation_holds_longer_than_narration():
    def total(style):
        return sum(float(v) for v in PAUSE_MARKER_RE.findall(annotate(AFFIRMATIONS[1], style)))

    assert total("meditation") > total("narration")


def test_sound_tags_dropped_for_models_that_would_read_them():
    out = annotate(MICRO_GESTURES[3], "meditation", sound_tags=False)
    assert "(" not in out
    assert "<#" in out  # silence survives; only the tags go


# ── authored markup ──────────────────────────────────────────────────


def test_hand_written_markup_is_preserved_not_doubled():
    authored = "Respira hondo (exhale)<#3.00#> y descansa."
    out = annotate(authored, "meditation")
    assert out.count("(exhale)") == 1
    assert "<#3.00#>" in out


def test_has_markup_detects_both_forms():
    assert has_markup("hola <#1.00#> mundo")
    assert has_markup("hola (sighs) mundo")
    assert not has_markup("hola mundo")


def test_strip_markup_removes_everything():
    assert strip_markup("hola (inhale)<#1.00#> mundo") == "hola mundo"


def test_strip_markup_can_keep_pauses():
    assert strip_markup("hola (inhale)<#1.00#> mundo", pauses=False) == "hola <#1.00#> mundo"


# ── API-legal output ─────────────────────────────────────────────────


def test_sanitize_merges_consecutive_markers():
    assert sanitize("hola <#0.50#> <#0.50#> mundo") == "hola<#1.00#> mundo"


def test_sanitize_drops_edge_markers():
    assert sanitize("<#1.00#> hola mundo <#2.00#>") == "hola mundo"


def test_sanitize_clamps_out_of_range_durations():
    assert sanitize("hola <#0.00#> mundo") == "hola<#0.01#> mundo"
    assert sanitize("hola <#500#> mundo") == "hola<#99.99#> mundo"


@pytest.mark.parametrize("text", MICRO_GESTURES + AFFIRMATIONS)
@pytest.mark.parametrize("style", ["affirmation", "meditation", "narration"])
def test_every_script_is_legal_markup(text, style):
    out = annotate(text, style)

    # No marker at either end.
    assert not out.startswith("<#") and not out.endswith("#>")

    # No two markers in a row, whitespace between or not.
    assert "#><#" not in out.replace(" ", "")

    # Every duration inside the documented range.
    for value in PAUSE_MARKER_RE.findall(out):
        assert 0.01 <= float(value) <= 99.99

    # Annotation only inserts: strip it back out and the words are intact.
    assert strip_markup(out) == text
