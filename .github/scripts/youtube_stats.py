#!/usr/bin/env python3
"""Fetch YouTube channel statistics and render them into README.md as badges.

Reads the official YouTube Data API v3, then rewrites everything between the
YOUTUBE-STATS marker comments. The numbers are baked into static shields.io
URLs, so the rendered README has no runtime dependency on any third party:
if this workflow ever stops running, the last known-good counts simply stay
put instead of decaying into a broken badge.

Exits non-zero on any API failure so a broken key shows up as a red run
rather than silently writing nothing.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/channels"
TAG = "YOUTUBE-STATS"
TIMEOUT = 30


def die(message):
    """Fail the workflow run with an annotation GitHub surfaces in the UI."""
    print("::error::%s" % message)
    sys.exit(1)


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        die("%s is not set. Add it under Settings > Secrets and variables > Actions." % name)
    return value


def fetch_statistics(channel_id, api_key):
    query = urllib.parse.urlencode(
        {"part": "statistics", "id": channel_id, "key": api_key}
    )
    request = urllib.request.Request(
        "%s?%s" % (API, query), headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # Read Google's reason, but never echo the URL: it carries the key.
        try:
            detail = json.load(exc).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        if exc.code in (400, 403):
            die(
                "YouTube API rejected the request (HTTP %d): %s "
                "The key is usually expired, restricted to the wrong API, or out of quota."
                % (exc.code, detail)
            )
        die("YouTube API returned HTTP %d: %s" % (exc.code, detail))
    except urllib.error.URLError as exc:
        die("Could not reach the YouTube API: %s" % exc.reason)

    items = payload.get("items") or []
    if not items:
        die(
            "YouTube API returned no channel for id %s. "
            "Check YOUTUBE_CHANNEL_ID is the UC... channel id, not the @handle." % channel_id
        )
    stats = items[0].get("statistics") or {}
    if "subscriberCount" not in stats:
        die("Channel %s hides its subscriber count, so there is nothing to publish." % channel_id)
    return stats


def humanise(count):
    """1234567 -> 1.2M, 33414 -> 33.4K, 210 -> 210."""
    number = int(count)
    for limit, suffix in ((1_000_000, "M"), (1_000, "K")):
        if number >= limit:
            scaled = "%.1f" % (number / limit)
            return scaled.replace(".0", "") + suffix
    return str(number)


def badge(label, value, color, label_color, logo):
    """A static shields badge with the value baked in."""
    def esc(text):
        # shields path syntax: '-' doubles, '_' doubles, space becomes '_'
        return urllib.parse.quote(
            str(text).replace("-", "--").replace("_", "__").replace(" ", "_"), safe=""
        )

    params = urllib.parse.urlencode(
        {"style": "for-the-badge", "logo": logo, "logoColor": "white", "labelColor": label_color}
    )
    return "https://custom-icon-badges.demolab.com/badge/%s-%s-%s?%s" % (
        esc(label),
        esc(value),
        esc(color),
        params,
    )


def render(stats, channel_url):
    subscribers = humanise(stats["subscriberCount"])
    views = humanise(stats.get("viewCount", 0))
    videos = stats.get("videoCount", "0")
    rows = [
        ("SUBSCRIBE", subscribers, "#E05D44", "CE4630", "video", channel_url + "?sub_confirmation=1"),
        ("Views", views, "#E1AD0E", "C79600", "eye", channel_url),
        ("Videos", videos, "#4C1F7A", "3B1760", "play", channel_url + "/videos"),
    ]
    markup = "\n".join(
        '<a href="%s"><img alt="%s" src="%s"/></a>'
        % (link, label, badge(label, value, color, label_color, logo))
        for label, value, color, label_color, logo, link in rows
    )
    return "\n" + markup + "\n"


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
        print("Statistics unchanged; leaving %s alone." % readme_path)
        return False

    with open(readme_path, "w", encoding="utf-8") as handle:
        handle.write(updated)
    print("Updated %s." % readme_path)
    return True


def main():
    channel_id = require_env("YOUTUBE_CHANNEL_ID")
    api_key = require_env("YOUTUBE_API_KEY")
    readme_path = os.environ.get("README_PATH", "README.md")
    channel_url = os.environ.get("CHANNEL_URL", "https://www.youtube.com/@HackProKP")

    stats = fetch_statistics(channel_id, api_key)
    print(
        "subscribers=%s views=%s videos=%s"
        % (stats["subscriberCount"], stats.get("viewCount"), stats.get("videoCount"))
    )

    changed = splice(readme_path, render(stats, channel_url))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("changed=%s\n" % ("true" if changed else "false"))


if __name__ == "__main__":
    main()
