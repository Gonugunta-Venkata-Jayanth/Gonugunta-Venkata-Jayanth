#!/usr/bin/env python3
"""Generate self-hosted GitHub profile cards (no third-party card services).

Outputs into ./dist:
  stats.svg     - public repos, stars, commits/contributions (last year), followers
  languages.svg - top languages by bytes across owned, non-fork repos
  activity.svg  - contributions for the last 30 days as an area chart

Also refreshes the "Latest weekly builds" block in README.md between
<!-- WEEKLY:START --> and <!-- WEEKLY:END -->.

Uses GITHUB_TOKEN when present (Actions), otherwise unauthenticated REST.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request

USER = os.environ.get("GH_USER", "Gonugunta-Venkata-Jayanth")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = "dist"

BG, CARD, FG, MUTED, ACCENT, ACCENT2 = "#1a1b27", "#1f2335", "#c0caf5", "#787c99", "#7aa2f7", "#bb9af7"
LANG_COLORS = {
    "Python": "#3572A5", "Jupyter Notebook": "#DA5B0B", "HTML": "#e34c26", "JavaScript": "#f1e05a",
    "Java": "#b07219", "Go": "#00ADD8", "CSS": "#563d7c", "Shell": "#89e051", "Dockerfile": "#384d54",
    "TypeScript": "#3178c6", "C++": "#f34b7d", "C": "#555555", "PowerShell": "#012456", "HCL": "#844FBA",
}


# Notebook JSON (embedded outputs/images) dwarfs real code, so it is left out of byte share.
SKIP_LANGS = {"Jupyter Notebook"}


def get(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER})
    if TOKEN and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    return json.loads(body) if "json" in accept else body


def esc(s):
    return html.escape(str(s), quote=True)


def card(width, height, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
<style>
.t{{font:600 17px 'Segoe UI',Ubuntu,sans-serif;fill:{ACCENT}}}
.l{{font:400 13px 'Segoe UI',Ubuntu,sans-serif;fill:{FG}}}
.m{{font:400 11px 'Segoe UI',Ubuntu,sans-serif;fill:{MUTED}}}
.v{{font:700 22px 'Segoe UI',Ubuntu,sans-serif;fill:{FG}}}
.f{{animation:fade .8s ease-in-out both}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
</style>
<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>
<text x="24" y="34" class="t">{esc(title)}</text>
{body}
</svg>"""


def contributions():
    page = get(f"https://github.com/users/{USER}/contributions", accept="text/html")
    days = {}
    for m in re.finditer(r'data-date="(\d{4}-\d{2}-\d{2})" id="(contribution-day-component-[\d-]+)"', page):
        days[m.group(2)] = [m.group(1), 0]
    for m in re.finditer(r'for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)<', page):
        cid, text = m.group(1), m.group(2)
        n = re.match(r"(\d+) contribution", text)
        if cid in days and n:
            days[cid][1] = int(n.group(1))
    total = None
    t = re.search(r"([\d,]+)\s+contributions?\s+in the last year", page)
    if t:
        total = int(t.group(1).replace(",", ""))
    series = sorted((d, c) for d, c in days.values())
    if total is None:
        total = sum(c for _, c in series)
    return series, total


def streaks(series):
    today = dt.date.today()
    cur = best = run = 0
    for d, c in series:
        run = run + 1 if c > 0 else 0
        best = max(best, run)
    # current streak: allow today to be empty
    for d, c in reversed(series):
        if dt.date.fromisoformat(d) == today and c == 0:
            continue
        if c > 0:
            cur += 1
        else:
            break
    return cur, best


def main():
    os.makedirs(OUT, exist_ok=True)
    user = get(f"https://api.github.com/users/{USER}")
    repos = []
    page = 1
    while True:
        batch = get(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    own = [r for r in repos if not r.get("fork")]
    stars = sum(r.get("stargazers_count", 0) for r in own)
    series, total = contributions()
    cur, best = streaks(series)

    # ---- language totals
    totals = {}
    for r in own:
        if r.get("archived"):
            continue
        try:
            langs = get(r["languages_url"])
        except Exception:
            continue
        for k, v in langs.items():
            if k in SKIP_LANGS:
                continue
            totals[k] = totals.get(k, 0) + v
    # ---- stats card
    items = [
        ("Public repos", len(own)), ("Contributions (1y)", total),
        ("Active days (1y)", sum(1 for _, c in series if c > 0)), ("Repos updated (30d)", sum(1 for r in own if (r.get("pushed_at") or "") >= (dt.date.today() - dt.timedelta(days=30)).isoformat())),
        ("Languages used", len(totals)), ("Coding since", (user.get("created_at") or "????")[:4]),
    ]
    body = []
    for i, (label, val) in enumerate(items):
        x = 24 + (i % 3) * 150
        y = 78 + (i // 3) * 62
        body.append(f'<g class="f" style="animation-delay:{i*120}ms"><text x="{x}" y="{y}" class="v">{esc(val)}</text>'
                    f'<text x="{x}" y="{y+20}" class="m">{esc(label)}</text></g>')
    updated = dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y")
    body.append(f'<text x="24" y="190" class="m">Generated by GitHub Actions · {updated}</text>')
    open(f"{OUT}/stats.svg", "w").write(card(480, 205, f"{user.get('name') or USER} · GitHub Stats", "\n".join(body)))

    # ---- languages card
    top = sorted(totals.items(), key=lambda kv: -kv[1])[:8]
    allsum = sum(totals.values()) or 1
    top = [kv for kv in top if kv[1] / allsum >= 0.002]
    s = sum(v for _, v in top) or 1
    bar, x, rows = [], 24, []
    for name, v in top:
        w = 432 * v / s
        bar.append(f'<rect x="{x:.1f}" y="52" width="{max(w,1):.1f}" height="10" fill="{LANG_COLORS.get(name, ACCENT2)}"/>')
        x += w
    for i, (name, v) in enumerate(top):
        cx = 24 + (i % 2) * 220
        cy = 88 + (i // 2) * 26
        rows.append(f'<g class="f" style="animation-delay:{i*90}ms"><circle cx="{cx+5}" cy="{cy-4}" r="5" fill="{LANG_COLORS.get(name, ACCENT2)}"/>'
                    f'<text x="{cx+16}" y="{cy}" class="l">{esc(name)} <tspan class="m">{v*100/s:.1f}%</tspan></text></g>')
    body = f'<clipPath id="c"><rect x="24" y="52" width="432" height="10" rx="5"/></clipPath><g clip-path="url(#c)">{"".join(bar)}</g>' + "".join(rows)
    open(f"{OUT}/languages.svg", "w").write(card(480, 205, "Most Used Languages (excl. notebooks)", body))

    # ---- activity card (contributions per month, last 12 months)
    months = {}
    for d, c in series:
        months[d[:7]] = months.get(d[:7], 0) + c
    keys = sorted(months)[-12:]
    W, H, L, T, PW, PH = 900, 260, 50, 64, 826, 140
    mx = max([months[k] for k in keys] + [1])
    bw = PW / max(len(keys), 1)
    grid = "".join(f'<line x1="{L}" x2="{L+PW}" y1="{T+PH*k/4:.1f}" y2="{T+PH*k/4:.1f}" stroke="#2a2e45"/>'
                   f'<text x="{L-10}" y="{T+PH*k/4+4:.1f}" text-anchor="end" class="m">{round(mx*(4-k)/4)}</text>' for k in range(5))
    bars = []
    for i, k in enumerate(keys):
        v = months[k]
        h = PH * v / mx
        x = L + i * bw + bw * 0.18
        lab = dt.date.fromisoformat(k + "-01").strftime("%b")
        bars.append(f'<g class="f" style="animation-delay:{i*60}ms"><rect x="{x:.1f}" y="{T+PH-h:.1f}" width="{bw*0.64:.1f}" height="{max(h,1.5):.1f}" rx="4" fill="url(#g)"/>'
                    f'<text x="{x+bw*0.32:.1f}" y="{T+PH-h-6:.1f}" text-anchor="middle" class="m">{v if v else ""}</text>'
                    f'<text x="{x+bw*0.32:.1f}" y="{T+PH+20}" text-anchor="middle" class="m">{lab}</text></g>')
    body = (f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ACCENT2}"/>'
            f'<stop offset="1" stop-color="{ACCENT}"/></linearGradient></defs>{grid}{"".join(bars)}'
            f'<text x="{W-24}" y="34" text-anchor="end" class="m">{total} contributions in the last year</text>')
    open(f"{OUT}/activity.svg", "w").write(card(W, H, "Contributions by Month", body))

    # ---- weekly builds block in README
    try:
        items = get(f"https://api.github.com/repos/{USER}/weekly-builds/contents")
        builds = sorted([i["name"] for i in items if i["type"] == "dir" and re.match(r"\d{4}-\d{2}-\d{2}-", i["name"])], reverse=True)[:5]
    except Exception:
        builds = []
    if builds:
        lines = [f"- `{b[:10]}` · [{b[11:].replace('-', ' ').title()}](https://github.com/{USER}/weekly-builds/tree/main/{b})" for b in builds]
    else:
        lines = ["- 🚧 First build lands this week. Follow [weekly-builds](https://github.com/%s/weekly-builds) to see it." % USER]
    readme = open("README.md").read()
    new = re.sub(r"(<!-- WEEKLY:START -->).*?(<!-- WEEKLY:END -->)", "\\1\n" + "\n".join(lines) + "\n\\2", readme, flags=re.S)
    if new != readme:
        open("README.md", "w").write(new)
    print(f"repos={len(own)} stars={stars} contributions={total} streak={cur}/{best} langs={[n for n,_ in top]} builds={len(builds)}")


if __name__ == "__main__":
    sys.exit(main())
