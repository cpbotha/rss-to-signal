import datetime
import json
import os
from pathlib import Path

import pytest

from rss_to_signal import main


def test_og_image():
    fname = main.get_og_image("https://cpbotha.net/2025/03/11/weekly-head-voices-259-backbone/")
    assert fname is not None
    assert fname.endswith(".webp")
    assert Path(fname).exists()


def test_e2e_skip_signal(request, capsys):
    # ensure that cwd == tests/
    os.chdir(request.fspath.dirname)
    # ensure that there is no state file
    Path("test.state.json").unlink(missing_ok=True)
    # ensure that there is a cfg
    cfg = {"feed_url": "https://cpbotha.net/index.xml", "dests": [{"username": "fakey"}]}
    with Path("test.cfg.json").open("w") as f:
        json.dump(cfg, f)
    # bleh
    main.main("test", start_date=datetime.datetime(2025, 6, 11, 0, 0, 0), skip_signal=True)
    captured = capsys.readouterr()

    assert captured.out.find("➖ Skip ") >= 0
    assert captured.out.find("🚀 Process") >= 0
    assert captured.out.find("signal-cli send") >= 0


# I have an .env file at project top-level, and pytest-dotenv is installed
@pytest.mark.skipif(
    not (os.environ.get("TEST_SIGNAL_GROUP_ID") and os.environ.get("TEST_SIGNAL_USERNAME")),
    reason="TEST_SIGNAL_* environment variables not set",
)
def test_e2e(request, capsys):
    # ensure that cwd == tests/
    os.chdir(request.fspath.dirname)
    # ensure that there is no state file
    Path("test.state.json").unlink(missing_ok=True)
    # ensure that there is a cfg
    username = os.environ.get("TEST_SIGNAL_USERNAME")
    group = os.environ["TEST_SIGNAL_GROUP_ID"]
    cfg = {
        "feed_url": "https://cpbotha.net/index.xml",
        "dests": [{"username": username}, {"group": group}],
    }
    with Path("test.cfg.json").open("w") as f:
        json.dump(cfg, f)
    # bleh
    main.main("test", start_date=datetime.datetime(2025, 6, 11, 0, 0, 0))
    captured = capsys.readouterr()

    assert captured.out.find("➖ Skip ") >= 0
    assert captured.out.find("🚀 Process") >= 0
    assert captured.out.find(f"About to notify -u {username}") >= 0
    assert captured.out.find(f"About to notify -g {group}") >= 0
