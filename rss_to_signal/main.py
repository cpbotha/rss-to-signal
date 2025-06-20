# rss-to-signal send new (unseen) recent rss posts to signal using signal-cli
# copyright 2025 Charl P. Botha <cpbotha@vxlabs.com>

# process:
# 1. download latest rss, using feedparser's etag mechanism
# 2. process any items with date later than latest date, either latest from seen list or from argument
# 3. for each item, prepare url, title, description, og:image for thumbnail so we can invoke signal-cli
# notes:
# we need to store seen post urls (the item ids) and their dates, as well as last etag
# quickest to just maintain a json file which is deserialised into dict

# TODO:
# - retrieve og:image from post into temporary file
# - tests

import datetime
import json
from pathlib import Path
from typing import cast

import feedparser
import httpx
import typer
from bs4 import BeautifulSoup
from dateutil.parser import parse

LPED = "latest_processed_entry_date"


app = typer.Typer()


def get_og_image(url):
    with httpx.Client(timeout=10) as client:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        tag = soup.find("meta", property="og:image")
        if tag and tag.get("content"):
            return tag["content"]
    return None


def process_entry(e, no_signal=False):
    # https://feedparser.readthedocs.io/en/latest/common-rss-elements.html#accessing-common-item-elements
    print(f"handling {e.id} and {e.link} with {e.published}")


def default(obj):
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _state_fn(profile: str):
    return f"{profile}.state.json"


def _config_fn(profile: str):
    return f"{profile}.cfg.json"


def dump_state(state, profile: str):
    json.dump(state, Path(_state_fn(profile)).open("w"), indent=2, default=default)


def object_hook(o):
    if LPED in o:
        o[LPED] = parse(o[LPED])
    if "modified" in o:
        o["modified"] = parse(o["modified"])
    return o


@app.command()
def main(profile: str, start_date: datetime.datetime | None = None):
    cfg = json.load(Path(_config_fn(profile)).open())
    feed_url = cfg["feed_url"]

    try:
        state = json.load(Path(_state_fn(profile)).open(), object_hook=object_hook)
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
            process_entry(e)
            if state.get(LPED) is None or e_date > state[LPED]:
                state[LPED] = e_date
            dump_state(state, profile)

    # we only save the etag / feed modified date if we've processed all the entries
    if d.etag:
        state["etag"] = d.etag
    if d.modified:
        state["modified"] = parse(cast(str, d.modified))

    dump_state(state, profile)


if __name__ == "__main__":
    # typer.run(main)
    app()
