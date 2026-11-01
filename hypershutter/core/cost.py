"""Cost and time estimate shown to the user before any API call.

Prices per million tokens (input, output), Anthropic first-party, as of 2026-10.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypershutter.core.sheets import SheetLayout, image_tokens, sheet_shapes

MODELS = {
    "claude-opus-5-5": {"label": "Opus 5.5 (default, most capable)", "price": (4.00, 20.00)},
    "claude-sonnet-5-5": {"label": "Sonnet 5.5 (half the cost)", "price": (2.00, 10.00)},
    "claude-haiku-5-5": {"label": "Haiku 5.5 (cheapest)", "price": (0.10, 0.50)},
}
DEFAULT_MODEL = "claude-opus-5-5"     # the user's choice: accuracy over cost

PROMPT_TOKENS_PER_CLIP = 900     # instructions + clip metadata (the instructions are cached)
OUTPUT_TOKENS_PER_CLIP = 450     # the structured description
SECONDS_PER_CALL = 12.0
PARALLEL_CALLS = 8


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


def estimate(frames_per_clip: list[int], model: str = DEFAULT_MODEL, layout: SheetLayout = SheetLayout()) -> Estimate:
    sheets = [s for n in frames_per_clip for s in sheet_shapes(n, layout)]
    image_in = sum(image_tokens(w, h) for w, h in sheets)
    n = len(frames_per_clip)
    tin = image_in + n * PROMPT_TOKENS_PER_CLIP
    tout = n * OUTPUT_TOKENS_PER_CLIP
    pin, pout = MODELS[model]["price"]
    return Estimate(clips=n, frames=sum(frames_per_clip), sheets=len(sheets), input_tokens=tin, output_tokens=tout,
                    cost_usd=round(tin / 1e6 * pin + tout / 1e6 * pout, 2),
                    minutes=round(n / PARALLEL_CALLS * SECONDS_PER_CALL / 60, 1), model=model)
