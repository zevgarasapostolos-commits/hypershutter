from hypershutter.core import config
from hypershutter.core.greeklish import folder_name


def test_app_support_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path / "hs"))
    assert config.app_support_dir() == tmp_path / "hs"
    assert config.cache_dir("frames").is_dir()


def test_presets_load_and_name():
    for kind in ("baptism", "wedding", "event"):
        p = config.load_preset(kind)
        assert p["event_type"] == kind
        assert p["typical_parts"], kind
        style = p["naming"]["greeklish_style"]
        unusable = p["naming"]["unusable"]
        assert folder_name(unusable["number"], unusable["label"], style=style) == "99 AXRISTA"
