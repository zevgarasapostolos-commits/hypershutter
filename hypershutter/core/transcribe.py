"""What is said in the ceremony masters (Greek), with word times: Whisper large-v3-turbo on Apple
Silicon (mlx), as in the videographer's own workflow (docs/workflow-baptism.md §4.2).

Used to find the phrases for the film scenes («Βαπτίζεται ο δούλος του Θεού…», «Στέφεται…») and
to cut off-ritual talk in the ροή. Runs locally; nothing is uploaded. Results are cached per file
in Application Support.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from hypershutter.core import config, store

MODEL = "mlx-community/whisper-large-v3-turbo"
PROMPTS = {
    "baptism": "Ακολουθία του Αγίου Βαπτίσματος. Του Κυρίου δεηθώμεν. Αποτάσσομαι. Συντάσσομαι. "
               "Πιστεύω εις ένα Θεόν, Πατέρα, παντοκράτορα. Βαπτίζεται ο δούλος του Θεού.",
    "wedding": "Ακολουθία του Γάμου. Ευλογητός ο Θεός ημών. Αρραβωνίζεται ο δούλος του Θεού. "
               "Στέφεται ο δούλος του Θεού. Κύριε ο Θεός ημών, δόξη και τιμή στεφάνωσον αυτούς. "
               "Ησαΐα χόρευε. Το κοινό ποτήριο.",
}


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[tuple[float, float, str]]


def _norm(s: str) -> str:
    """Lower case without accents, for phrase search in Greek."""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def _cache(path: Path, size: int, mtime: float, prompt: str) -> Path:
    key = store.file_key(path.name, size, mtime) + "|" + MODEL + "|" + prompt
    return config.cache_dir("transcripts") / (hashlib.sha1(key.encode()).hexdigest()[:24] + ".json")


def transcribe(path: Path, event_type: str = "baptism") -> list[Segment]:
    path = Path(path)
    st = path.stat()
    prompt = PROMPTS.get(event_type, PROMPTS["baptism"])
    cf = _cache(path, st.st_size, st.st_mtime, prompt)
    if not cf.exists():
        import mlx_whisper
        ff = config.find_tool("ffmpeg")
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "a.wav"
            subprocess.run([ff, "-v", "error", "-y", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "16000",
                            "-af", "highpass=f=100,loudnorm", str(wav)], check=True)
            r = mlx_whisper.transcribe(str(wav), path_or_hf_repo=MODEL, language="el", word_timestamps=True,
                                       condition_on_previous_text=False, initial_prompt=prompt,
                                       no_speech_threshold=0.8)
        segs = [{"start": s["start"], "end": s["end"], "text": s["text"].strip(),
                 "words": [[w["start"], w["end"], w["word"]] for w in s.get("words", [])]}
                for s in r.get("segments", [])]
        cf.write_text(json.dumps(segs, ensure_ascii=False))
    return [Segment(s["start"], s["end"], s["text"], [tuple(w) for w in s["words"]])
            for s in json.loads(cf.read_text()) if not HALLUCINATION.search(_norm(s["text"]))]


HALLUCINATION = re.compile(r"υποτιτλοι|authorwave|subtitles|ευχαριστω που παρακολουθησατε")


def find(segments: list[Segment], pattern: str) -> list[Segment]:
    """Segments whose text matches the pattern (accents and case ignored)."""
    rx = re.compile(_norm(pattern))
    return [s for s in segments if rx.search(_norm(s.text))]


# phrases that mark the moments of each ceremony
MOMENTS = {
    "immersion": r"βαπτιζεται",
    "naming": r"δουλον σου|προσκαλεσαι|ονομα",
    "crowning": r"στεφεται|στεφανω ?σον|δοξη και τιμη",
    "rings": r"αρραβωνιζεται",
    "isaiah": r"ησαια χορευε",
    "common_cup": r"ποτηριον σωτηριου|κοινον ποτηριον",
}


LITURGY = re.compile(
    r"κυρι|θεο|θεε|δεηθ|αμην|ευλογ|δοξα|ελεησ|πατρο|υιου|πνευματ|ειρην|στεφ|ησαι|ποτηρ|δουλ|βαπτι|ονοματ|"
    r"χριστ|αγι|πιστευ|αποτασσ|συντασσ|προσκυν|αλληλουι|σοφια|ορθοι|ευαγγελ|αποστολ|πρεσβει|θεοτοκ|παναγ|"
    r"βασιλει|τριαδ|σωτηρ|χαρι|ελεος|ιερε|μακαρ|ψαλ|εκκλησ|αρραβ|γαμ|συζυγ|ανδρ|γυναικ")


def ritual_ranges(segments: list[Segment], start_after: float = 0.0, min_len: float = 5.0,
                  glue: float = 4.0) -> list[tuple[float, float]]:
    """Stretches of the ceremony to keep: runs of liturgical speech, with short non-liturgical
    bits inside a run kept as glue; off-ritual talk between runs is cut (workflow §6.2)."""
    runs: list[list[float]] = []
    for seg in segments:
        if seg.end <= start_after:
            continue
        liturgical = bool(LITURGY.search(_norm(seg.text)))
        a = max(seg.start, start_after)
        if liturgical:
            if runs and a - runs[-1][1] <= glue:
                runs[-1][1] = seg.end
            else:
                runs.append([a, seg.end])
        elif runs and seg.end - seg.start <= glue and a - runs[-1][1] <= 1.0:
            runs[-1][1] = seg.end                      # a short word of instruction inside the ritual
    return [(a, b) for a, b in runs if b - a >= min_len]
