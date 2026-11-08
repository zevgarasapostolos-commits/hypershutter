"""Cost and time estimate shown to the user before any API call.

Prices per million tokens (input, output), Anthropic first-party, as of 2026-10.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypershutter.core.sheets import SheetLayout, image_tokens, sheet_shapes

MODELS = {
    "claude-opus-5-5": {"label": "Opus 5.5 (default, most capable)", "price": (4.00, 20.00)},
}
DEFAULT_MODEL = "claude-opus-5-5"     # the user's choice: accuracy over cost

PROMPT_TOKENS_PER_CLIP = 900     # instructions + clip metadata (the instructions are cached)
OUTPUT_TOKENS_PER_CLIP = 450     # the structured description
SECONDS_PER_CALL = 12.0
PARALLEL_CALLS = 8
# pass 2, measured on the 073 baptism (267 clips): 37.8K input, 11.5K output tokens, 90 s
STRUCTURE_IN = (3000, 150)       # fixed, per clip
STRUCTURE_OUT = (2000, 45)
STRUCTURE_SECONDS = (10.0, 0.3)


@dataclass
class Estimate:
    clips: int
    frames: int
    sheets: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    minutes: float
    model: str
    cached: int = 0                  # clips already described with this model: free


def estimate(frames_per_clip: list[int], model: str = DEFAULT_MODEL, layout: SheetLayout = SheetLayout(),
             total_clips: int | None = None) -> Estimate:
    """Pass 1 for the clips in `frames_per_clip` (those not described yet) + pass 2 over all clips."""
    sheets = [s for n in frames_per_clip for s in sheet_shapes(n, layout)]
    image_in = sum(image_tokens(w, h) for w, h in sheets)
    n = len(frames_per_clip)
    total = n if total_clips is None else total_clips
    tin = image_in + n * PROMPT_TOKENS_PER_CLIP + STRUCTURE_IN[0] + total * STRUCTURE_IN[1]
    tout = n * OUTPUT_TOKENS_PER_CLIP + STRUCTURE_OUT[0] + total * STRUCTURE_OUT[1]
    pin, pout = MODELS[model]["price"]
    seconds = n / PARALLEL_CALLS * SECONDS_PER_CALL + STRUCTURE_SECONDS[0] + total * STRUCTURE_SECONDS[1]
    return Estimate(clips=n, frames=sum(frames_per_clip), sheets=len(sheets), input_tokens=tin, output_tokens=tout,
                    cost_usd=round(tin / 1e6 * pin + tout / 1e6 * pout, 2), minutes=round(seconds / 60, 1),
                    model=model, cached=total - n)
