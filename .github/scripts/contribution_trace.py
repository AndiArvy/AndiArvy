import json
import os
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen


WIDTH = 1000
HEIGHT = 238
PALETTE = {
    "NONE": "#21323d",
    "FIRST_QUARTILE": "#3c6359",
    "SECOND_QUARTILE": "#679479",
    "THIRD_QUARTILE": "#abd3a2",
    "FOURTH_QUARTILE": "#ffd278",
}
QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            weekday
            contributionLevel
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_calendar(login, token):
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-contribution-trace",
        },
    )
    with urlopen(request, timeout=25) as response:
        result = json.load(response)

    if result.get("errors"):
        raise RuntimeError(result["errors"][0]["message"])
    return result["data"]["user"]["contributionsCollection"]["contributionCalendar"]


def calendar_graph(weeks):
    step = min(17, 912 // len(weeks))
    left = (WIDTH - step * len(weeks)) // 2
    marks = []
    totals = []
    month = None
    label_x = -100
    for column, week in enumerate(weeks):
        x = left + column * step
        days = week["contributionDays"]
        first_date = date.fromisoformat(days[0]["date"])
        if first_date.month != month and x - label_x >= 48:
            month = first_date.month
            label_x = x
            marks.append(f'<text class="month" x="{x}" y="76">{first_date:%b}</text>')

        for day in days:
            y = 87 + day["weekday"] * 15
            fill = PALETTE[day["contributionLevel"]]
            marks.append(f'<rect x="{x}" y="{y}" width="{step - 4}" height="12" rx="2.5" fill="{fill}"/>')
        totals.append(sum(day["contributionCount"] for day in days))

    peak = max(1, *totals)
    marks.append(f'<path class="baseline" d="M{left} 216H{WIDTH - left}"/>')
    points = " ".join(
        f"{left + index * step + (step - 4) // 2},{216 - round(19 * count / peak)}"
        for index, count in enumerate(totals)
    )
    marks.append(f'<polyline class="signal" points="{points}"/>')
    return "\n".join(marks)


def render(calendar=None):
    if calendar is None:
        status = "Awaiting the first GitHub Actions run"
        graph = """
<rect x="39" y="68" width="922" height="150" fill="url(#grid)"/>
<path class="baseline" d="M39 147H961"/>
<path class="signal" stroke-width="2.2" d="M39 147H114V120H171V147H244V171H298V147H356V108H411V147H475V174H516V120H577V147H663V169H708V147H765V113H824V147H886V163H923V147H961"/>
"""
    else:
        status = f'{calendar["totalContributions"]:,} contributions · past year'
        weeks = calendar["weeks"]
        graph = calendar_graph(weeks) if weeks else '<path class="baseline" d="M39 147H961"/>'

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title status">
<title id="title">Contribution trace</title>
<desc id="status">{status}</desc>
<defs>
  <linearGradient id="sweep">
    <stop offset="0" stop-color="#ffd278" stop-opacity="0"/>
    <stop offset="1" stop-color="#ffd278" stop-opacity=".2"/>
  </linearGradient>
  <pattern id="grid" x="39" y="68" width="23" height="18" patternUnits="userSpaceOnUse">
    <path d="M23 0H0V18" fill="none" stroke="#263945" stroke-width=".8"/>
  </pattern>
  <clipPath id="screen"><rect x="39" y="68" width="922" height="153"/></clipPath>
</defs>
<style>
  .title {{ fill: #f4f7fa; font: 600 26px system-ui, sans-serif; }}
  .status {{ fill: #ffda93; font: 17px ui-monospace, monospace; }}
  .month {{ fill: #a8c1cc; font: 14px ui-monospace, monospace; }}
  .baseline {{ fill: none; stroke: #314953; }}
  .signal {{ fill: none; stroke: #ffd278; stroke-linecap: round; stroke-linejoin: round; }}
  .probe {{ opacity: 0; animation: sweep 4.5s ease-in-out; }}
  @keyframes sweep {{
    0% {{ transform: translateX(0); opacity: 0; }}
    10%, 90% {{ opacity: 1; }}
    100% {{ transform: translateX(1036px); opacity: 0; }}
  }}
  @media (prefers-reduced-motion: reduce) {{ .probe {{ animation: none; }} }}
</style>
<rect x=".5" y=".5" width="999" height="237" rx="12" fill="#101b24" stroke="#526371"/>
<circle cx="43" cy="35" r="4" fill="#ffd278"/>
<text class="title" x="59" y="44">Contribution trace</text>
<text class="status" x="960" y="43" text-anchor="end">{status}</text>
<path class="baseline" d="M39 58H961"/>
{graph}
<g clip-path="url(#screen)">
  <g class="probe">
    <rect x="-76" y="68" width="115" height="153" fill="url(#sweep)"/>
    <path d="M39 68V221" stroke="#ffd278" stroke-width="1.5"/>
  </g>
</g>
</svg>
"""


if __name__ == "__main__":
    calendar = fetch_calendar(os.environ["PROFILE_LOGIN"], os.environ["GH_TOKEN"])
    Path("assets/contributions.svg").write_text(render(calendar), encoding="utf-8")
