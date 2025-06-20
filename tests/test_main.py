from pathlib import Path
from rss_to_signal import main


def test_og_image():
    fname = main.get_og_image("https://cpbotha.net/2025/03/11/weekly-head-voices-259-backbone/")
    assert fname is not None
    assert fname.endswith(".webp")
    assert Path(fname).exists()
