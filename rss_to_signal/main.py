# rss-to-signal send new (unseen) recent rss posts to signal using signal-cli
# copyright 2025 Charl P. Botha <cpbotha@vxlabs.com>

# process:
# 1. download latest rss, using feedparser's etag mechanism
# 2. process any items with date later than latest date, either latest from seen list or from argument
# 3. for each item, prepare url, title, description, og:image for thumbnail so we can invoke signal-cli

import datetime
import json
import mimetypes
import subprocess
import tempfile
from pathlib import Path
from typing import cast

import feedparser
import httpx
import typer
from bs4 import BeautifulSoup
from dateutil.parser import parse
from rich import print
from typing_extensions import Annotated

LPED = "latest_processed_entry_date"


app = typer.Typer()


def get_og_image(url):
    with httpx.Client(timeout=10) as client:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        tag = soup.find("meta", property="og:image")
        if tag and (img_url := cast(str, tag.get("content"))):
            # this is a url to a png / webp
            # download to temporary file
            resp = client.get(img_url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            suffix = mimetypes.guess_extension(content_type) or img_url[-4:]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(resp.content)
                return f.name
    return None


def process_entry(entry: feedparser.FeedParserDict, dests: list, dry_run=False, signal_cmd: str | None = None):
    og_image = get_og_image(entry.link)
    if og_image is not None:
        img_part = f' --preview-image "{og_image}"'
    else:
        img_part = ""

    if signal_cmd is None:
        signal_cmd = "signal-cli"

    for dest in dests:
        if not dest.get("enabled", True):
            continue

        # at the end append either phone, -u username, -g group_id
        dest_part = None
        if "phone" in dest:
            dest_part = dest["phone"]
        elif "username" in dest:
            dest_part = "-u " + dest["username"]
        elif "group" in dest:
            dest_part = "-g " + dest["group"]
        else:
            # no destination
            continue

        # https://feedparser.readthedocs.io/en/latest/common-rss-elements.html#accessing-common-item-elements
        cmd = f'{signal_cmd} send -m {entry.link} --preview-url {entry.link} --preview-title "{entry.title}" --preview-description "{entry.description}"'
        if img_part is not None:
            cmd += img_part

        cmd += " " + dest_part

        print(f"About to notify {dest_part} of {entry.link}")
        if dry_run:
            print(f"Not running: {cmd}")
        else:
            # run cmd, raise exception if error
            subprocess.run(cmd, shell=True, check=True)


def default(obj):
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _state_fn(feed_name: str):
    return f"{feed_name}.state.json"


def _config_fn(feed_name: str):
    return f"{feed_name}.cfg.json"


def dump_state(state, feed_name: str):
    json.dump(state, Path(_state_fn(feed_name)).open("w"), indent=2, default=default)


def object_hook(o):
    if LPED in o:
        o[LPED] = parse(o[LPED])
    if "modified" in o:
        o["modified"] = parse(o["modified"])
    return o


@app.command()
def main(
    feed_name: Annotated[
        str,
        typer.Argument(
            help="Name of the feed you want to monitor; used only for naming `<feed_name>.cfg.json` and `<feed_name>.state.json`"
        ),
    ],
    start_date: Annotated[datetime.datetime | None, typer.Option(help="Only process posts newer than this")] = None,
    skip_signal: Annotated[
        bool, typer.Option(help="Do everything *except* sending out the Signal notifications")
    ] = False,
):
    """Monitor RSS feeds for new posts and send notification with link preview via signal-cli

    Before running this, create a config file named <feed_name>.cfg.json with at least the following contents:

    {"feed_url": "https://some.site.com/index.xml", "dests": [{"group": "<group id from `signal-cli listGroups`>"}]}

    Each dest can be group, username or phone.

    """
    cfg = json.load(Path(_config_fn(feed_name)).open())
    feed_url = cfg["feed_url"]
    dests = cfg.get("dests", [])
    # optionally set this if you need to pass account, or the full path, e.g.
    # "signal_cmd": "/usr/local/bin/signal-cli -a MY_ACCOUNT"
    # the default value is just "signal-cli" which should work in many cases
    signal_cmd = cfg.get("signal_cmd")

    try:
        state = json.load(Path(_state_fn(feed_name)).open(), object_hook=object_hook)
    except FileNotFoundError:
        state = {}

    # unpack state here
    latest_processed_entry_date: datetime.datetime | None = state.get(LPED, None)
    prev_feed_etag = state.get("etag")
    prev_feed_modified = state.get("modified")

    d = feedparser.parse(feed_url, etag=prev_feed_etag, modified=prev_feed_modified)
    # https://feedparser.readthedocs.io/en/latest/http-etag.html
    # get and store both, prefer to use etag
    if d.status == 304:
        print("Nothing has changed since the previous feed fetch")
        return

    for e in sorted(d.entries, key=lambda x: x.published_parsed):
        # published_parsed is a time.struct_time which has no TZ info
        # so we rather parse our own
        # print(e.id, parse(e.published).isoformat())
        # print(json.dumps(e, indent=2))
        e_date = parse(cast(str, e.published))
        if (latest_processed_entry_date is None or e_date > latest_processed_entry_date) and (
            start_date is None or e_date > start_date.replace(tzinfo=datetime.timezone.utc)
        ):
            print(f"🚀 Process {e.link} of {e.published}")
            process_entry(e, dests, skip_signal, signal_cmd)
            if state.get(LPED) is None or e_date > state[LPED]:
                state[LPED] = e_date
            dump_state(state, feed_name)
        else:
            print(f"➖ Skip {e.link} of {e.published}, older than latest processed date or older than start-date")

        print("\n")

    # we only save the etag / feed modified date if we've processed all the entries
    if d.etag:
        state["etag"] = d.etag
    if d.modified:
        state["modified"] = parse(cast(str, d.modified))

    dump_state(state, feed_name)


if __name__ == "__main__":
    app()
