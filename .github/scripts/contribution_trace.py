import json
import os
from datetime import date
from math import log1p, sin, tau
from pathlib import Path
from urllib.request import Request, urlopen


WIDTH = 1000
HEIGHT = 288
SCOPE_BASELINE = 224
READOUT_Y = 269
READOUT_ROW = 24
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


def waveform(totals, left, step):
    peak = log1p(max(totals)) or 1
    samples = 24
    points = [f"{left},{SCOPE_BASELINE}"]
    for index, count in enumerate(totals):
        x = left + index * step
        if not count:
            points.append(f"{x + step},{SCOPE_BASELINE}")
            continue

        cycles = 0.65 + 2.1 * log1p(count) / peak
        for sample in range(1, samples + 1):
            fraction = sample / samples
            # Taper each segment to the baseline at the week boundaries.
            amplitude = 13 * min(1, 8 * fraction, 8 * (1 - fraction))
            y = SCOPE_BASELINE - amplitude * sin(tau * cycles * fraction)
            points.append(f"{x + step * fraction:.2f},{y:.2f}")
    return ' '.join(points)


def calendar_graph(weeks):
    step = min(17, 912 // len(weeks))
    travel = step * len(weeks)
    left = (WIDTH - travel) // 2
    marks = []
    totals = []
    readings = []
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
        total = sum(day["contributionCount"] for day in days)
        totals.append(total)
        unit = 'contribution' if total == 1 else 'contributions'
        readings.append(f"Week of {first_date:%b} {first_date.day}, {first_date.year} · {total:,} {unit}")

    labels = '\n'.join(
        f'<text x="39" y="{READOUT_Y + index * READOUT_ROW}">{reading}</text>'
        for index, reading in enumerate(readings)
    )
    cells = '\n'.join(marks)
    return f"""{cells}
<polyline class="signal" points="{waveform(totals, left, step)}"/>
<g style="--weeks: {len(weeks)}; --scan-travel: {travel}px; --readout-travel: {-len(weeks) * READOUT_ROW}px">
  <g clip-path="url(#screen)">
    <rect class="scan-week" x="{left}" y="84" width="{step - 1}" height="108" rx="3"/>
    <g class="probe">
      <rect x="{left - 72}" y="68" width="72" height="177" fill="url(#sweep)"/>
      <path d="M{left} 68V245" stroke="#ffd278" stroke-width="1.5"/>
    </g>
  </g>
  <g clip-path="url(#readout-window)">
    <g class="readout readings">
      {labels}
    </g>
    <text class="readout latest" x="39" y="{READOUT_Y}">{readings[-1]}</text>
  </g>
</g>
<text class="legend" x="961" y="{READOUT_Y}" text-anchor="end">Pulse density · contributions per week</text>"""


def render(calendar=None):
    if calendar is None:
        status = "Awaiting the first GitHub Actions run"
        weeks = []
    else:
        status = f'{calendar["totalContributions"]:,} contributions · past year'
        weeks = calendar["weeks"]

    graph = calendar_graph(weeks) if weeks else ''
    description = f'{status}. Denser waves show more contributions in a week.' if weeks else status

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title status">
<title id="title">Contribution trace</title>
<desc id="status">{description}</desc>
<defs>
  <linearGradient id="sweep">
    <stop offset="0" stop-color="#ffd278" stop-opacity="0"/>
    <stop offset="1" stop-color="#ffd278" stop-opacity=".2"/>
  </linearGradient>
  <pattern id="grid" x="39" y="203" width="23" height="10.5" patternUnits="userSpaceOnUse">
    <path d="M23 0H0V10.5" fill="none" stroke="#263945" stroke-width=".8"/>
  </pattern>
  <clipPath id="screen"><rect x="39" y="68" width="922" height="177"/></clipPath>
  <clipPath id="readout-window"><rect x="39" y="252" width="450" height="{READOUT_ROW}"/></clipPath>
</defs>
<style>
  svg {{ --scan-duration: 18s; }}
  .title {{ fill: #f4f7fa; font: 600 26px system-ui, sans-serif; }}
  .status {{ fill: #ffda93; font: 17px ui-monospace, monospace; }}
  .month {{ fill: #a8c1cc; font: 14px ui-monospace, monospace; }}
  .readout {{ fill: #ffda93; font: 16px ui-monospace, monospace; }}
  .legend {{ fill: #a8c1cc; font: 14px ui-monospace, monospace; }}
  .baseline {{ fill: none; stroke: #314953; }}
  .signal {{ fill: none; stroke: #ffd278; stroke-width: 1.35; stroke-linecap: round; stroke-linejoin: round; }}
  .probe {{ animation: sweep var(--scan-duration) linear infinite; }}
  .scan-week {{
    fill: #ffd278; fill-opacity: .09; stroke: #ffd278; stroke-opacity: .65;
    animation: sweep var(--scan-duration) steps(var(--weeks), end) infinite;
  }}
  .readings {{ animation: advance-readout var(--scan-duration) steps(var(--weeks), end) infinite; }}
  .latest {{ display: none; }}
  @keyframes sweep {{ to {{ transform: translateX(var(--scan-travel)); }} }}
  @keyframes advance-readout {{ to {{ transform: translateY(var(--readout-travel)); }} }}
  @media (prefers-reduced-motion: reduce) {{
    .probe, .scan-week, .readings {{ animation: none; display: none; }}
    .latest {{ display: inline; }}
  }}
</style>
<rect x=".5" y=".5" width="999" height="{HEIGHT - 1}" rx="12" fill="#101b24" stroke="#526371"/>
<circle cx="43" cy="35" r="4" fill="#ffd278"/>
<text class="title" x="59" y="44">Contribution trace</text>
<text class="status" x="960" y="43" text-anchor="end">{status}</text>
<path class="baseline" d="M39 58H961"/>
<rect x="39" y="203" width="922" height="42" rx="4" fill="#0c161f"/>
<rect x="39" y="203" width="922" height="42" rx="4" fill="url(#grid)"/>
<path class="baseline" d="M39 {SCOPE_BASELINE}H961"/>
{graph}
</svg>
"""


if __name__ == "__main__":
    calendar = fetch_calendar(os.environ["PROFILE_LOGIN"], os.environ["GH_TOKEN"])
    Path("assets/contributions.svg").write_text(render(calendar), encoding="utf-8")
