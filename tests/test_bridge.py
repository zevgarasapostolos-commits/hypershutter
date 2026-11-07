"""The app's API without a window: the calls every screen makes on start work and stay offline."""
import json

import pytest

from hypershutter.app.bridge import Bridge
from hypershutter.core import credentials


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path / "support"))
    monkeypatch.setattr(credentials, "get_api_key", lambda: None)       # never touch the real Keychain
    return Bridge(lambda path: path, pick_folder=lambda: None, start_queue=False)


def test_screens_load_without_a_project(bridge):
    info = bridge.info()
    assert info["version"] and info["onboarded"] is False and "key" not in info
    s = bridge.settings()
    assert s["key"] == "" and s["model"] == info["default_model"]
    assert {p["id"] for p in s["proxy_presets"]} == {"prores_proxy", "h264"}
    assert {p["id"] for p in bridge.export_presets()} == {"h264_1080_review", "hevc_4k_archive", "prores_422_lt"}
    assert isinstance(bridge.drives(), list) and bridge.drives()[0]["name"] == "Macintosh HD"
    assert bridge.jobs_status()["counts"] == {} and bridge.ingest_history() == []
    json.dumps([bridge.drives(), bridge.jobs_status(), s])                # everything is JSON for the UI


def test_settings_are_saved_and_checked(bridge):
    s = bridge.save_settings({"frame_interval": 4, "use_sound": False, "warn_gb": 80, "not_a_setting": 1})
    assert s["frame_interval"] == 4 and s["use_sound"] is False and "not_a_setting" not in s
    with pytest.raises(ValueError):
        bridge.set_api_key("too short")
    with pytest.raises(RuntimeError):
        bridge.export_plan("h264_1080_review")                          # no project open
