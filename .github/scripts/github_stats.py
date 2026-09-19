#!/usr/bin/env python3
"""Bake GitHub counts into README.md as static badges.

Counted badges used to come from shields.io, which meant every count change
produced a URL GitHub's camo proxy had never seen and had to fetch on demand.
When shields is rate limited or down, that fetch fails and the badge renders
broken - which is what happened to the Repos and Featured star badges.

So the numbers are fetched here at CI time with the run's own GITHUB_TOKEN,
drawn into SVGs by badge.py, and committed to the repository. They are then
referenced from raw.githubusercontent.com, which GitHub serves directly -
it does not camo-proxy its own domain - as image/svg+xml. No badge service
is involved at render time at all.

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

import badge as badge_svg

API = "https://api.github.com"
USER = os.environ.get("GITHUB_USER", "at0m-b0mb")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
BADGE_DIR = os.environ.get("BADGE_DIR", ".github/badges")
RAW_BASE = "https://raw.githubusercontent.com/%s/%s/%s/%s" % (USER, USER, BRANCH, BADGE_DIR)
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


def write_badge(name, svg):
    path = os.path.join(BADGE_DIR, name)
    os.makedirs(BADGE_DIR, exist_ok=True)
    existing = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            existing = handle.read()
    if existing != svg:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(svg)
    return path


def badge_url(name, version):
    """Raw URLs are served by GitHub itself, so nothing is proxied or cached
    by camo. The ?v= carries the value so a changed count busts any cache."""
    return "%s/%s?v=%s" % (RAW_BASE, name, urllib.parse.quote(str(version), safe=""))


def render_header(followers, stars, repo_count):
    rows = [
        ("Follow", followers, "#236ad3", "#1155ba", False,
         "https://github.com/%s?tab=followers" % USER),
        ("Stars", stars, "#55960c", "#488207", True,
         "https://github.com/%s?tab=repositories&sort=stargazers" % USER),
        ("Repos", repo_count, "#FFD700", "#C79600", False,
         "https://github.com/%s?tab=repositories" % USER),
    ]
    markup = []
    for label, value, color, label_color, star, link in rows:
        name = "%s.svg" % label.lower()
        write_badge(name, badge_svg.render(label, value, color, label_color, star=star))
        markup.append(
            '<a href="%s"><img alt="%s: %s" src="%s"/></a>'
            % (link, label, value, badge_url(name, value))
        )
    return "\n" + "\n".join(markup) + "\n"


def render_featured(featured, stars_by_repo):
    lines = ["| Project | What it does | |", "| :--- | :--- | :--- |"]
    for entry in featured:
        repo = entry["repo"]
        count = stars_by_repo.get(repo.lower())
        if count is None:
            die("Featured repo %s was not found among %s's public repos." % (repo, USER))
        name = "star-%s.svg" % repo.lower()
        write_badge(
            name,
            badge_svg.render("", count, "#FFD700", "#FFD700", style="flat", star=True),
        )
        lines.append(
            "| **[%s](https://github.com/%s/%s)** | %s | ![%s stars](%s) |"
            % (entry["name"], USER, repo, entry["blurb"], count, badge_url(name, count))
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
