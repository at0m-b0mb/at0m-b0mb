#!/usr/bin/env python3
"""Render recent YouTube videos as cards into README.md.

Replaces DenverCoder1/github-readme-youtube-cards, which sourced its video
list from https://www.youtube.com/feeds/videos.xml. YouTube retired that RSS
endpoint (it now returns 404 for every channel), so the action silently
produced an empty section from 2026-09-08 onward.

This reads the same information from the YouTube Data API instead:
  channels      -> the channel's uploads playlist   (1 quota unit)
  playlistItems -> the most recent videos           (1 quota unit)
  videos        -> durations                        (1 quota unit)

Card images still come from ytcards.demolab.com, so the rendered result is
visually identical to what was there before.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "https://www.googleapis.com/youtube/v3"
TAG = "YOUTUBE-CARDS"
TIMEOUT = 30

CARD_BASE = os.environ.get("CARD_BASE_URL", "https://ytcards.demolab.com/")
WIDTH = os.environ.get("CARD_WIDTH", "250")
RADIUS = os.environ.get("BORDER_RADIUS", "5")
MAX_TITLE_LINES = os.environ.get("MAX_TITLE_LINES", "2")
LANG = os.environ.get("LANG_CODE", "en")

DARK = {"background_color": "#0d1117", "title_color": "#ffffff", "stats_color": "#dedede"}
LIGHT = {"background_color": "#ffffff", "title_color": "#24292f", "stats_color": "#57606a"}


def die(message):
    print("::error::%s" % message)
    sys.exit(1)


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        die("%s is not set. Add it under Settings > Secrets and variables > Actions." % name)
    return value


def api(endpoint, params, api_key):
    params = dict(params)
    params["key"] = api_key
    url = "%s/%s?%s" % (BASE, endpoint, urllib.parse.urlencode(params))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Never echo the URL back: it carries the key.
        try:
            detail = json.load(exc).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        die(
            "YouTube API %s failed (HTTP %d): %s%s"
            % (
                endpoint,
                exc.code,
                detail,
                "  The key is usually expired, not enabled for YouTube Data API v3, or out of quota."
                if exc.code in (400, 403)
                else "",
            )
        )
    except urllib.error.URLError as exc:
        die("Could not reach the YouTube API (%s): %s" % (endpoint, exc.reason))


def uploads_playlist(channel_id, api_key):
    data = api("channels", {"part": "contentDetails", "id": channel_id}, api_key)
    items = data.get("items") or []
    if not items:
        die(
            "No channel found for id %s. It must be the UC... channel id, not the @handle."
            % channel_id
        )
    try:
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except KeyError:
        die("Channel %s exposes no uploads playlist." % channel_id)


def recent_videos(playlist_id, limit, api_key):
    data = api(
        "playlistItems",
        {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": str(limit)},
        api_key,
    )
    videos = []
    for item in data.get("items") or []:
        snippet = item.get("snippet") or {}
        details = item.get("contentDetails") or {}
        video_id = details.get("videoId") or (snippet.get("resourceId") or {}).get("videoId")
        title = snippet.get("title") or ""
        if not video_id or title in ("Private video", "Deleted video"):
            continue
        published = details.get("videoPublishedAt") or snippet.get("publishedAt") or ""
        videos.append({"id": video_id, "title": title, "published": published})
    return videos


def iso8601_seconds(value):
    """PT1H2M3S -> 3723. Returns 0 for anything unparseable."""
    match = re.fullmatch(
        r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", (value or "").strip()
    )
    if not match:
        return 0
    days, hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def durations(video_ids, api_key):
    if not video_ids:
        return {}
    data = api("videos", {"part": "contentDetails", "id": ",".join(video_ids)}, api_key)
    return {
        item["id"]: iso8601_seconds((item.get("contentDetails") or {}).get("duration"))
        for item in data.get("items") or []
    }


def unix_timestamp(iso):
    try:
        return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").timestamp())
    except (ValueError, TypeError):
        return 0


def card_url(video, theme, duration):
    params = {
        "id": video["id"],
        "title": video["title"],
        "lang": LANG,
        "timestamp": unix_timestamp(video["published"]),
        "background_color": theme["background_color"],
        "title_color": theme["title_color"],
        "stats_color": theme["stats_color"],
        "max_title_lines": MAX_TITLE_LINES,
        "width": WIDTH,
        "border_radius": RADIUS,
    }
    if duration:
        params["duration"] = duration
    return CARD_BASE + "?" + urllib.parse.urlencode(params)


def escape(text):
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render(videos, lengths):
    cards = []
    for video in videos:
        duration = lengths.get(video["id"], 0)
        title = escape(video["title"])
        cards.append(
            '<a href="https://www.youtube.com/watch?v=%s">\n'
            "  <picture>\n"
            '    <source media="(prefers-color-scheme: dark)" srcset="%s">\n'
            '    <img src="%s" alt="%s" title="%s">\n'
            "  </picture>\n"
            "</a>"
            % (
                video["id"],
                escape(card_url(video, DARK, duration)),
                escape(card_url(video, LIGHT, duration)),
                title,
                title,
            )
        )
    return "\n" + "\n".join(cards) + "\n"


def splice(readme_path, block):
    with open(readme_path, encoding="utf-8") as handle:
        original = handle.read()

    begin = "<!-- BEGIN %s -->" % TAG
    end = "<!-- END %s -->" % TAG
    if original.count(begin) != 1 or original.count(end) != 1:
        die("Expected exactly one %s / %s marker pair in %s." % (begin, end, readme_path))

    head, _, rest = original.partition(begin)
    _, _, tail = rest.partition(end)
    updated = head + begin + block + end + tail

    if updated == original:
        print("Cards unchanged; leaving %s alone." % readme_path)
        return False

    with open(readme_path, "w", encoding="utf-8") as handle:
        handle.write(updated)
    print("Updated %s." % readme_path)
    return True


def main():
    channel_id = require_env("YOUTUBE_CHANNEL_ID")
    api_key = require_env("YOUTUBE_API_KEY")
    readme_path = os.environ.get("README_PATH", "README.md")
    try:
        limit = max(1, min(50, int(os.environ.get("MAX_VIDEOS", "6"))))
    except ValueError:
        limit = 6

    playlist = uploads_playlist(channel_id, api_key)
    videos = recent_videos(playlist, limit, api_key)
    if not videos:
        die("The uploads playlist %s came back empty, so there are no cards to write." % playlist)
    print("Found %d video(s): %s" % (len(videos), ", ".join(v["id"] for v in videos)))

    lengths = durations([v["id"] for v in videos], api_key)
    changed = splice(readme_path, render(videos, lengths))

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("changed=%s\n" % ("true" if changed else "false"))
            handle.write("count=%d\n" % len(videos))


if __name__ == "__main__":
    main()
