import json
import os
from datetime import date
from math import exp, log1p, sin, tau
from pathlib import Path
from urllib.request import Request, urlopen


WIDTH = 1000
HEIGHT = 426
SPECTRUM_TOP = 246
SPECTRUM_BOTTOM = 385
SPECTRUM_HEIGHT = SPECTRUM_BOTTOM - SPECTRUM_TOP
BAND_COUNT = 40
FRAME_SECONDS = 0.09
READOUT_Y = 228
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


def spectrum_frames(weekly_counts, totals):
    peak = log1p(max(totals)) or 1
    frequencies = [band / (BAND_COUNT - 1) for band in range(BAND_COUNT)]
    frames = []
    for counts, total in zip(weekly_counts, totals):
        activity = log1p(total) / peak
        daily_peak = log1p(max(counts)) or 1
        for day, count in enumerate(counts):
            # The calendar drives a visual signal on a relative frequency scale.
            # Busier weeks reach higher bands and daily counts drive each pulse.
            transient = log1p(count) / daily_peak
            envelope = activity ** 0.65 * (0.30 + 0.66 * transient ** 0.6)
            center = 0.14 + 0.64 * activity
            spread = 0.13 + 0.11 * activity
            phase = day / len(counts)
            levels = []
            for frequency in frequencies:
                bass = 0.70 * exp(-0.5 * ((frequency - 0.12) / 0.14) ** 2)
                mids = exp(-0.5 * ((frequency - center) / spread) ** 2)
                ripple = 0.64 + 0.36 * sin(tau * (2.8 * frequency + phase)) ** 2
                levels.append(envelope * max(bass, mids) * ripple)
            frames.append(levels)
    return frames


def animate_transform(kind, values, timing, mode='linear'):
    return (f'<animateTransform attributeName="transform" type="{kind}" '
            f'values="{";".join(values)}" calcMode="{mode}" {timing}/>')


def render_spectrum(frames, first, latest, timing):
    elements = []
    band_step = 902 / BAND_COUNT
    for band, levels in enumerate(zip(*frames)):
        x = 49 + band * band_step
        width = band_step - 4.5
        # Run the release over the previous loop too, so peak caps wrap smoothly.
        peak = 0
        peaks = []
        for level in levels + levels:
            peak = max(level, peak * 0.73 - 0.015)
            peaks.append(peak)
        peaks = peaks[len(levels):]

        bar = animate_transform('scale', (f'1 {level:.3f}' for level in (*levels, levels[0])), timing)
        cap = animate_transform('translate', (f'0 {-peak * SPECTRUM_HEIGHT:.2f}' for peak in (*peaks, peaks[0])), timing)
        latest_height = levels[latest] * SPECTRUM_HEIGHT
        elements.append(f"""  <g transform="translate({x:.2f} {SPECTRUM_BOTTOM})">
    <rect class="band-rail" y="{-SPECTRUM_HEIGHT}" width="{width:.2f}" height="{SPECTRUM_HEIGHT}" rx="2"/>
    <rect class="band motion" y="{-SPECTRUM_HEIGHT}" width="{width:.2f}" height="{SPECTRUM_HEIGHT}" rx="2" transform="scale(1 {levels[first]:.3f})">{bar}</rect>
    <rect class="peak motion" width="{width:.2f}" height="2.5" rx="1" transform="translate(0 {-peaks[first] * SPECTRUM_HEIGHT:.2f})">{cap}</rect>
    <rect class="band still" y="{-latest_height:.2f}" width="{width:.2f}" height="{latest_height:.2f}" rx="2"/>
  </g>""")
    return '\n'.join(elements)


def calendar_graph(weeks):
    step = min(17, 912 // len(weeks))
    travel = step * len(weeks)
    left = (WIDTH - travel) // 2
    marks = []
    weekly_counts = []
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

        counts = [0] * 7
        for day in days:
            y = 87 + day["weekday"] * 15
            fill = PALETTE[day["contributionLevel"]]
            marks.append(f'<rect x="{x}" y="{y}" width="{step - 4}" height="12" rx="2.5" fill="{fill}"/>')
            counts[day['weekday']] = day['contributionCount']
        total = sum(counts)
        weekly_counts.append(counts)
        totals.append(total)
        unit = 'contribution' if total == 1 else 'contributions'
        readings.append(f"Week of {first_date:%b} {first_date.day}, {first_date.year} · {total:,} {unit}")

    # Begin with a recent active week so the display has a signal on load.
    start_week = max(range(max(0, len(weeks) - 8), len(weeks)), key=totals.__getitem__)
    if not totals[start_week]:
        start_week = totals.index(max(totals))
    start_day = weekly_counts[start_week].index(max(weekly_counts[start_week]))
    first = start_week * 7 + start_day
    latest = (len(weeks) - 1) * 7 + weekly_counts[-1].index(max(weekly_counts[-1]))
    frames = spectrum_frames(weekly_counts, totals)
    timing = f'begin="{-first * FRAME_SECONDS:.2f}s" dur="{len(frames) * FRAME_SECONDS:.2f}s" repeatCount="indefinite"'
    sweep = animate_transform('translate', ['0 0', f'{travel} 0'], timing)
    highlight = animate_transform('translate', (f'{index * step} 0' for index in range(len(weeks))), timing, 'discrete')
    readout = animate_transform('translate', (f'0 {-index * READOUT_ROW}' for index in range(len(weeks))), timing, 'discrete')
    labels = '\n'.join(
        f'<text x="961" y="{READOUT_Y + index * READOUT_ROW}">{reading}</text>'
        for index, reading in enumerate(readings)
    )
    cells = '\n'.join(marks)
    return f"""{cells}
<g class="motion" clip-path="url(#calendar-screen)">
  <rect class="scan-week" x="{left}" y="84" width="{step - 1}" height="108" rx="3" transform="translate({start_week * step} 0)">{highlight}</rect>
  <g class="probe" transform="translate({first * step / 7:.2f} 0)">
    {sweep}
    <rect x="{left - 72}" y="68" width="72" height="125" fill="url(#sweep)"/>
    <path d="M{left} 68V193" stroke="#ffd278" stroke-width="1.5"/>
  </g>
</g>
<g class="readout" clip-path="url(#readout-window)" text-anchor="end">
  <g class="motion readings" transform="translate(0 {-start_week * READOUT_ROW})">
    {readout}
    {labels}
  </g>
  <text class="still" x="961" y="{READOUT_Y}">{readings[-1]}</text>
</g>
<g clip-path="url(#spectrum-screen)">
{render_spectrum(frames, first, latest, timing)}
</g>"""


def render(calendar=None):
    if calendar is None:
        status = "Awaiting the first GitHub Actions run"
        weeks = []
    else:
        status = f'{calendar["totalContributions"]:,} contributions · past year'
        weeks = calendar["weeks"]

    graph = calendar_graph(weeks) if weeks else ''
    description = f'{status}. The animated spectrum represents daily contributions in the highlighted week.' if weeks else status

    return f"""<svg xmlns="http://www.w3.org/2000/svg" id="reduced-motion" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title status">
<title id="title">Contribution spectrum</title>
<desc id="status">{description}</desc>
<defs>
  <linearGradient id="sweep">
    <stop offset="0" stop-color="#ffd278" stop-opacity="0"/>
    <stop offset="1" stop-color="#ffd278" stop-opacity=".2"/>
  </linearGradient>
  <linearGradient id="band-color" x1="0" y1="1" x2="0" y2="0">
    <stop offset="0" stop-color="#288e77"/>
    <stop offset=".70" stop-color="#84d7ac"/>
    <stop offset="1" stop-color="#ffe2a5"/>
  </linearGradient>
  <pattern id="grid" x="39" y="{SPECTRUM_TOP}" width="23" height="23" patternUnits="userSpaceOnUse">
    <path d="M23 0H0V23" fill="none" stroke="#263945" stroke-width=".8"/>
  </pattern>
  <clipPath id="calendar-screen"><rect x="39" y="68" width="922" height="126"/></clipPath>
  <clipPath id="readout-window"><rect x="480" y="211" width="482" height="{READOUT_ROW}"/></clipPath>
  <clipPath id="spectrum-screen"><rect x="39" y="{SPECTRUM_TOP}" width="922" height="{SPECTRUM_HEIGHT}"/></clipPath>
</defs>
<style>
  .title {{ fill: #f4f7fa; font: 600 26px system-ui, sans-serif; }}
  .status {{ fill: #ffda93; font: 17px ui-monospace, monospace; }}
  .month {{ fill: #a8c1cc; font: 14px ui-monospace, monospace; }}
  .panel-title {{ fill: #f4f7fa; font: 600 17px system-ui, sans-serif; }}
  .readout {{ fill: #ffda93; font: 16px ui-monospace, monospace; }}
  .axis {{ fill: #a8c1cc; font: 14px ui-monospace, monospace; }}
  .baseline {{ fill: none; stroke: #314953; }}
  .scan-week {{ fill: #ffd278; fill-opacity: .09; stroke: #ffd278; stroke-opacity: .65; }}
  .band-rail {{ fill: #a8c1cc; fill-opacity: .045; }}
  .band {{ fill: url(#band-color); }}
  .peak {{ fill: #ffe2a5; }}
  .still {{ display: none; }}
  #reduced-motion:target .motion {{ display: none; }}
  #reduced-motion:target .still {{ display: inline; }}
  @media (prefers-reduced-motion: reduce) {{
    .motion {{ display: none; }}
    .still {{ display: inline; }}
  }}
</style>
<rect x=".5" y=".5" width="999" height="{HEIGHT - 1}" rx="12" fill="#101b24" stroke="#526371"/>
<circle cx="43" cy="35" r="4" fill="#ffd278"/>
<text class="title" x="59" y="44">Contribution spectrum</text>
<text class="status" x="960" y="43" text-anchor="end">{status}</text>
<path class="baseline" d="M39 58H961"/>
<text class="panel-title" x="39" y="{READOUT_Y}">Activity spectrum</text>
<rect x="39" y="{SPECTRUM_TOP}" width="922" height="{SPECTRUM_HEIGHT}" rx="4" fill="#0c161f"/>
<rect x="39" y="{SPECTRUM_TOP}" width="922" height="{SPECTRUM_HEIGHT}" rx="4" fill="url(#grid)"/>
{graph}
<path class="baseline" d="M39 {SPECTRUM_BOTTOM}H961"/>
<text class="axis" x="22" y="315.5" text-anchor="middle" transform="rotate(-90 22 315.5)">Relative amplitude</text>
<text class="axis" x="39" y="406">Low frequency</text>
<text class="axis" x="961" y="406" text-anchor="end">High frequency</text>
</svg>
"""


if __name__ == "__main__":
    calendar = fetch_calendar(os.environ["PROFILE_LOGIN"], os.environ["GH_TOKEN"])
    Path("assets/contributions.svg").write_text(render(calendar), encoding="utf-8")
