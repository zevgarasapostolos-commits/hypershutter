"""Greek -> Greeklish (Latin, upper case) for folder and file names on disk.

Folder names are always Greeklish regardless of UI language, e.g.
"08 ΚΑΤΗΧΗΣΗ — ΡΟΗ" -> "08 KATIXISI - ROI". The ambiguous letters are
style options so the user's exact convention can be stored in the preset.
"""

from __future__ import annotations

import re
import unicodedata

# The user confirmed these defaults on 2026-11-01.
DEFAULT_STYLE = {
    "upsilon": "Y",       # Υ alone: "Y" (MYSTIRIO) or "I" (MISTIRIO)
    "au_eu": "phonetic",  # ΑΥ/ΕΥ: "phonetic" (EVRETIRIO, AFTOS) or "literal" (EYRETIRIO, AYTOS)
    "xi": "KS",           # Ξ: "KS" (DEKSIOSI) or "X" (DEXIOSI; collides with Χ -> X)
    "mp_nt": "literal",   # ΜΠ/ΝΤ/ΓΚ: "literal" (MP/NT/GK) or "phonetic" (B/D/G at word start)
}

_SINGLE = {
    "Α": "A", "Β": "V", "Γ": "G", "Δ": "D", "Ε": "E", "Ζ": "Z", "Η": "I", "Θ": "TH",
    "Ι": "I", "Κ": "K", "Λ": "L", "Μ": "M", "Ν": "N", "Ο": "O", "Π": "P", "Ρ": "R",
    "Σ": "S", "Τ": "T", "Φ": "F", "Χ": "X", "Ψ": "PS", "Ω": "O",
}
_VOICELESS = set("ΘΚΞΠΣΤΦΧΨ")
_GREEK = set(_SINGLE) | {"Ξ", "Υ"}
_DASHES = {"—": "-", "–": "-", "‒": "-", "−": "-"}


def _letters(text: str) -> list[tuple[str, bool]]:
    """Upper-case letters with accents removed; the flag marks a diaeresis (breaks diphthongs)."""
    out: list[tuple[str, bool]] = []
    for ch in unicodedata.normalize("NFD", text):
        if ch == "̈" and out:
            out[-1] = (out[-1][0], True)
        elif unicodedata.category(ch) != "Mn":
            up = "Σ" if ch == "ς" else ch.upper()
            out.append((_DASHES.get(up, up), False))
    return out


def to_greeklish(text: str, style: dict | None = None) -> str:
    st = {**DEFAULT_STYLE, **(style or {})}
    ls = _letters(text)
    res: list[str] = []
    i = 0
    while i < len(ls):
        c, _ = ls[i]
        nxt, nxt_dia = ls[i + 1] if i + 1 < len(ls) else ("", False)
        after = ls[i + 2][0] if i + 2 < len(ls) else ""
        word_start = i == 0 or ls[i - 1][0] not in _GREEK

        if c == "Ο" and nxt == "Υ" and not nxt_dia:
            res.append("OU"); i += 2; continue
        if c in "ΑΕΗ" and nxt == "Υ" and not nxt_dia:
            if st["au_eu"] == "phonetic":
                tail = "F" if (after in _VOICELESS or after not in _GREEK) else "V"
            else:
                tail = "Y"
            res.append(_SINGLE[c] + tail); i += 2; continue
        if st["mp_nt"] == "phonetic" and (c, nxt) in {("Μ", "Π"), ("Ν", "Τ"), ("Γ", "Κ")}:
            hard = {"Π": "B", "Τ": "D", "Κ": "G"}[nxt]
            res.append(hard if word_start else {"Π": "MB", "Τ": "ND", "Κ": "NG"}[nxt]); i += 2; continue
        if c == "Υ":
            res.append(st["upsilon"]); i += 1; continue
        if c == "Ξ":
            res.append(st["xi"]); i += 1; continue
        res.append(_SINGLE.get(c, c))
        i += 1
    return re.sub(r"\s+", " ", "".join(res)).strip()


def safe_folder_name(name: str) -> str:
    """'/' would create a subfolder and ':' shows as '/' in Finder; trailing dots/spaces break paths."""
    name = name.replace("/", "-").replace(":", "-")
    return re.sub(r"\s+", " ", name).strip().rstrip(".")


def folder_name(number: int, label: str, sub: str = "", style: dict | None = None) -> str:
    """folder_name(8, "ΚΑΤΗΧΗΣΗ — B-ROLL", "a") -> "08a KATIXISI - B-ROLL"."""
    return safe_folder_name(f"{number:02d}{sub} {to_greeklish(label, style)}")
