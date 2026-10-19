"""Exact reflection silences, kept outside provider-generated speech."""

import re
import numpy as np

PAUSE_RE = re.compile(r"<#(\d+(?:\.\d{1,2})?)#>")


def split_directed_text(text):
    parts = PAUSE_RE.split(text)
    if any('<#' in part or '#>' in part for part in parts[::2]):
        raise ValueError("Use pause markers like <#2.5#> with at most two decimal places")
    if any(float(part) > 30 or float(part) < 0.01 for part in parts[1::2]):
        raise ValueError("Local pauses must be between 0.01 and 30 seconds")
    if sum(float(part) for part in parts[1::2]) > 600:
        raise ValueError("Total reflection silence cannot exceed 10 minutes")
    if not any(part.strip() for part in parts[::2]):
        raise ValueError("Add spoken text to the meditation")
    return parts


async def render_with_pauses(text, synthesize, sample_rate):
    parts = split_directed_text(text)
    output = []
    for index, part in enumerate(parts):
        if index % 2:
            output.append(np.zeros(round(float(part) * sample_rate), dtype=np.float32))
        elif part.strip():
            audio, rate = await synthesize(part.strip())
            if rate != sample_rate:
                raise RuntimeError("Provider changed sample rate within a directed recording")
            output.append(np.asarray(audio, dtype=np.float32))
    return np.concatenate(output), sample_rate
