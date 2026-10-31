import pytest

from hypershutter.core.greeklish import folder_name, safe_folder_name, to_greeklish


@pytest.mark.parametrize("greek, expected", [
    # the examples given in the project brief
    ("ΣΤΟΛΙΣΜΟΣ & CANDY BAR", "STOLISMOS & CANDY BAR"),
    ("ΚΑΤΗΧΗΣΗ — ΡΟΗ", "KATIXISI - ROI"),
    ("ΚΑΤΗΧΗΣΗ — B-ROLL", "KATIXISI - B-ROLL"),
    ("ΑΧΡΗΣΤΑ", "AXRISTA"),
    # accents, final sigma, lower case
    ("Βάφτιση", "VAFTISI"),
    ("ΛΕΠΤΟΜΕΡΕΙΕΣ (ΡΟΥΧΑ, ΛΑΜΠΑΔΑ, ΛΑΔΟΠΑΝΟ)", "LEPTOMEREIES (ROUXA, LAMPADA, LADOPANO)"),
    ("ΕΥΡΕΤΗΡΙΟ ΠΛΑΝΩΝ", "EVRETIRIO PLANON"),
    ("ΔΕΞΙΩΣΗ — ΧΩΡΟΣ & ΤΡΑΠΕΖΙΑ", "DEKSIOSI - XOROS & TRAPEZIA"),
    ("ΜΥΣΤΗΡΙΟ — ΡΟΗ", "MYSTIRIO - ROI"),
    ("ΦΩΤΟΓΡΑΦΗΣΗ ΓΟΝΕΩΝ", "FOTOGRAFISI GONEON"),
    ("DRONE", "DRONE"),
])
def test_default_style(greek, expected):
    assert to_greeklish(greek) == expected


def test_au_eu_voiceless_and_diaeresis():
    assert to_greeklish("ΑΥΤΟΣ") == "AFTOS"
    assert to_greeklish("ΑΥΛΗ") == "AVLI"
    assert to_greeklish("ΗΣΑΪΑ") == "ISAIA"          # Ϊ is not part of a diphthong
    assert to_greeklish("ΠΡΩΤΕΥΟΥΣΑ") == "PROTEVOUSA"


def test_style_options():
    style = {"upsilon": "I", "au_eu": "literal", "xi": "X", "mp_nt": "phonetic"}
    assert to_greeklish("ΜΥΣΤΗΡΙΟ", style) == "MISTIRIO"
    assert to_greeklish("ΕΥΡΕΤΗΡΙΟ", style) == "EYRETIRIO"
    assert to_greeklish("ΔΕΞΙΩΣΗ", style) == "DEXIOSI"
    assert to_greeklish("ΜΠΟΜΠΟΝΙΕΡΑ", style) == "BOMBONIERA"
    assert to_greeklish("ΝΤΥΣΙΜΟ", style) == "DISIMO"


def test_folder_names():
    assert folder_name(1, "ΣΤΟΛΙΣΜΟΣ & CANDY BAR") == "01 STOLISMOS & CANDY BAR"
    assert folder_name(8, "ΚΑΤΗΧΗΣΗ — B-ROLL", "a") == "08a KATIXISI - B-ROLL"
    assert folder_name(99, "ΑΧΡΗΣΤΑ") == "99 AXRISTA"


def test_safe_folder_name_never_nests():
    assert safe_folder_name("15 EVXES / SYNENTEFKSEIS ") == "15 EVXES - SYNENTEFKSEIS"
    assert "/" not in safe_folder_name("a/b:c")
