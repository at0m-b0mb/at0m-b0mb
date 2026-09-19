#!/usr/bin/env python3
"""Bake GitHub counts into README.md as static badges.

shields.io endpoints that perform a live upstream lookup - badge/dynamic/json
and github/stars/<repo> - were returning 504 through GitHub's camo proxy,
so those badges rendered as broken images. Static shields badges (a literal
label and message in the path) serve fine.

So this fetches the numbers here, at CI time, with the workflow's own
GITHUB_TOKEN (authenticated: 5000 requests/hour, no anonymous rate limit)
and writes them into static badge URLs. Nothing is looked up at render time,
and because the URL changes when a number changes, camo refetches instead of
serving a stale cached image.

Writes two marker blocks:
  GITHUB-STATS - the follower / star / repo badges in the header
  FEATURED     - the Featured Work table, from .github/data/featured.json
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
USER = os.environ.get("GITHUB_USER", "at0m-b0mb")
TIMEOUT = 30


def die(message):
    print("::error::%s" % message)
    sys.exit(1)


def api(path):
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "%s-profile-readme" % USER,
        },
    )
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", "Bearer %s" % token)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        remaining = exc.headers.get("X-RateLimit-Remaining")
        hint = ""
        if exc.code == 403 and remaining == "0":
            hint = "  Rate limit exhausted; the workflow should pass GITHUB_TOKEN."
        die("GitHub API %s failed (HTTP %d).%s" % (path, exc.code, hint))
    except urllib.error.URLError as exc:
        die("Could not reach the GitHub API (%s): %s" % (path, exc.reason))


def all_repos():
    repos, page = [], 1
    while page <= 10:
        batch = api("/users/%s/repos?per_page=100&page=%d" % (USER, page))
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def badge(label, message, color, label_color, logo):
    """Static shields badge: the value lives in the path, not in a live lookup."""

    def esc(text):
        return urllib.parse.quote(
            str(text).replace("-", "--").replace("_", "__").replace(" ", "_"), safe=""
        )

    query = urllib.parse.urlencode(
        {
            "style": "for-the-badge",
            "logo": logo,
            "logoColor": "white",
            "labelColor": label_color,
        }
    )
    return "https://img.shields.io/badge/%s-%s-%s?%s" % (
        esc(label),
        esc(message),
        esc(color),
        query,
    )


def render_header(followers, stars, repo_count):
    rows = [
        ("Follow", followers, "236ad3", "1155ba", "github", "https://github.com/%s?tab=followers" % USER),
        ("Stars", stars, "55960c", "488207", "star", "https://github.com/%s?tab=repositories&sort=stargazers" % USER),
        ("Repos", repo_count, "FFD700", "C79600", "github", "https://github.com/%s?tab=repositories" % USER),
    ]
    markup = "\n".join(
        '<a href="%s"><img alt="%s" src="%s"/></a>' % (link, label, badge(label, value, color, label_color, logo))
        for label, value, color, label_color, logo, link in rows
    )
    return "\n" + markup + "\n"


def render_featured(featured, stars_by_repo):
    lines = ["| Project | What it does | |", "| :--- | :--- | :--- |"]
    for entry in featured:
        repo = entry["repo"]
        count = stars_by_repo.get(repo.lower())
        if count is None:
            die("Featured repo %s was not found among %s's public repos." % (repo, USER))
        star = "https://img.shields.io/badge/%s-FFD700?style=flat&logo=star&logoColor=white" % (
            urllib.parse.quote(str(count), safe="")
        )
        lines.append(
            "| **[%s](https://github.com/%s/%s)** | %s | ![stars](%s) |"
            % (entry["name"], USER, repo, entry["blurb"], star)
        )
    return "\n" + "\n".join(lines) + "\n"


def splice(text, tag, block, path):
    begin, end = "<!-- BEGIN %s -->" % tag, "<!-- END %s -->" % tag
    if text.count(begin) != 1 or text.count(end) != 1:
        die("Expected exactly one %s / %s marker pair in %s." % (begin, end, path))
    head, _, rest = text.partition(begin)
    _, _, tail = rest.partition(end)
    return head + begin + block + end + tail


def main():
    readme_path = os.environ.get("README_PATH", "README.md")
    featured_path = os.environ.get("FEATURED_PATH", ".github/data/featured.json")

    profile = api("/users/%s" % USER)
    repos = all_repos()
    stars_by_repo = {r["name"].lower(): r["stargazers_count"] for r in repos}
    total_stars = sum(r["stargazers_count"] for r in repos if not r["fork"])

    with open(featured_path, encoding="utf-8") as handle:
        featured = json.load(handle)

    print(
        "followers=%d repos=%d stars=%d featured=%d"
        % (profile["followers"], profile["public_repos"], total_stars, len(featured))
    )

    with open(readme_path, encoding="utf-8") as handle:
        original = handle.read()

    updated = splice(
        original,
        "GITHUB-STATS",
        render_header(profile["followers"], total_stars, profile["public_repos"]),
        readme_path,
    )
    updated = splice(
        updated, "FEATURED", render_featured(featured, stars_by_repo), readme_path
    )

    changed = updated != original
    if changed:
        with open(readme_path, "w", encoding="utf-8") as handle:
            handle.write(updated)
        print("Updated %s." % readme_path)
    else:
        print("Counts unchanged; leaving %s alone." % readme_path)

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("changed=%s\n" % ("true" if changed else "false"))


if __name__ == "__main__":
    main()
