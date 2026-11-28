import json
import os
from datetime import date
from math import log1p, sin, tau
from pathlib import Path
from urllib.request import Request, urlopen


WIDTH = 1000
HEIGHT = 426
SCOPE_LEFT = 39
SCOPE_RIGHT = WIDTH - SCOPE_LEFT
SCOPE_TOP = 246
SCOPE_BOTTOM = 385
SCOPE_HEIGHT = SCOPE_BOTTOM - SCOPE_TOP
SCOPE_CENTER = (SCOPE_TOP + SCOPE_BOTTOM) / 2
WEEK_SECONDS = 1
SAMPLES_PER_DAY = 24
SAMPLES_PER_WEEK = 7 * SAMPLES_PER_DAY
HISTORY_SAMPLES = 10 * SAMPLES_PER_DAY
FREQUENCY_THRESHOLDS = ((24, 8), (17, 4), (12, 2))
HEARTBEAT_AMPLITUDE = 0.18
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


def frequency_for_week(total, day_count):
    for minimum_daily_count, frequency in FREQUENCY_THRESHOLDS:
        if total >= minimum_daily_count * day_count:
            return frequency
    return 1


def waveform_samples(weekly_counts, totals, frequencies):
    peak_amplitude = log1p(max(totals)) or 1
    samples = []
    for counts, total, frequency in zip(weekly_counts, totals, frequencies):
        activity = log1p(total) / peak_amplitude
        cycles = frequency * WEEK_SECONDS
        daily_peak = log1p(max(counts)) or 1
        for cycle in range(cycles):
            start = cycle * SAMPLES_PER_WEEK // cycles
            stop = (cycle + 1) * SAMPLES_PER_WEEK // cycles
            samples_per_cycle = stop - start
            start_day = start // SAMPLES_PER_DAY
            end_day = (stop - 1) // SAMPLES_PER_DAY + 1
            daily = log1p(max(counts[start_day:end_day])) / daily_peak
            amplitude = HEARTBEAT_AMPLITUDE + (1 - HEARTBEAT_AMPLITUDE) * activity ** 0.58 * (
                0.48 + 0.52 * daily ** 0.74
            )
            # Each cycle starts at the rising zero crossing, including at the loop seam.
            samples.extend(
                amplitude * sin(tau * index / samples_per_cycle)
                for index in range(samples_per_cycle)
            )
    return samples


def animate_transform(kind, values, timing, mode='linear'):
    return (f'<animateTransform attributeName="transform" type="{kind}" '
            f'values="{";".join(values)}" calcMode="{mode}" {timing}/>')


def render_waveform(samples, first, latest, timing):
    spacing = (SCOPE_RIGHT - SCOPE_LEFT) / HISTORY_SAMPLES
    # Prepend the previous loop's history so the trace stays full at wraparound.
    points = ' '.join(
        f'{index * spacing:.2f},{SCOPE_CENTER - samples[index % len(samples)] * 62:.2f}'
        for index in range(-HISTORY_SAMPLES, len(samples) + 1)
    )
    travel = animate_transform(
        'translate', [f'{SCOPE_RIGHT} 0', f'{SCOPE_RIGHT - len(samples) * spacing:.2f} 0'], timing,
    )
    return f"""<defs><polyline id="activity-wave" points="{points}"/></defs>
<g clip-path="url(#scope-screen)">
  <g class="motion wave-scroll" transform="translate({SCOPE_RIGHT - first * spacing:.2f} 0)">
    {travel}
    <use href="#activity-wave" class="wave-glow"/>
    <use href="#activity-wave" class="wave-line"/>
  </g>
  <use href="#activity-wave" class="still wave-line" transform="translate({SCOPE_RIGHT - latest * spacing:.2f} 0)"/>
</g>"""


def calendar_graph(weeks):
    step = min(17, 912 // len(weeks))
    travel = step * len(weeks)
    left = (WIDTH - travel) // 2
    marks = []
    weekly_counts = []
    totals = []
    frequencies = []
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
        frequency = frequency_for_week(total, len(days))
        weekly_counts.append(counts)
        totals.append(total)
        frequencies.append(frequency)
        unit = 'contribution' if total == 1 else 'contributions'
        readings.append(f"Week of {first_date:%b} {first_date.day}, {first_date.year} · {total:,} {unit} · {frequency} Hz")

    # Begin with a recent active week so the display has a signal on load.
    start_week = max(range(max(0, len(weeks) - 8), len(weeks)), key=totals.__getitem__)
    if not totals[start_week]:
        start_week = totals.index(max(totals))
    start_day = weekly_counts[start_week].index(max(weekly_counts[start_week]))
    first = start_week * SAMPLES_PER_WEEK + start_day * SAMPLES_PER_DAY + SAMPLES_PER_DAY // 2
    latest_day = weekly_counts[-1].index(max(weekly_counts[-1]))
    latest = (len(weeks) - 1) * SAMPLES_PER_WEEK + latest_day * SAMPLES_PER_DAY + SAMPLES_PER_DAY // 2
    samples = waveform_samples(weekly_counts, totals, frequencies)
    offset = first * WEEK_SECONDS / SAMPLES_PER_WEEK
    timing = f'begin="{-offset:.4f}s" dur="{len(weeks) * WEEK_SECONDS:.2f}s" repeatCount="indefinite"'
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
  <g class="probe" transform="translate({first * step / SAMPLES_PER_WEEK:.2f} 0)">
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
{render_waveform(samples, first, latest, timing)}"""


def render(calendar=None):
    if calendar is None:
        status = "Awaiting the first GitHub Actions run"
        weeks = []
    else:
        status = f'{calendar["totalContributions"]:,} contributions · past year'
        weeks = calendar["weeks"]

    graph = calendar_graph(weeks) if weeks else ''
    description = status
    if weeks:
        description += '. The scrolling sine wave follows the contribution calendar, with a small sinusoidal heartbeat during idle weeks.'

    return f"""<svg xmlns="http://www.w3.org/2000/svg" id="reduced-motion" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title status">
<title id="title">Contribution trace</title>
<desc id="status">{description}</desc>
<defs>
  <linearGradient id="sweep">
    <stop offset="0" stop-color="#ffd278" stop-opacity="0"/>
    <stop offset="1" stop-color="#ffd278" stop-opacity=".2"/>
  </linearGradient>
  <pattern id="grid" x="{SCOPE_LEFT}" y="{SCOPE_TOP}" width="46" height="23" patternUnits="userSpaceOnUse">
    <path d="M46 0H0V23" fill="none" stroke="#2d414c" stroke-width=".8"/>
  </pattern>
  <clipPath id="calendar-screen"><rect x="39" y="68" width="922" height="126"/></clipPath>
  <clipPath id="readout-window"><rect x="480" y="211" width="482" height="{READOUT_ROW}"/></clipPath>
  <clipPath id="scope-screen"><rect x="{SCOPE_LEFT}" y="{SCOPE_TOP}" width="{SCOPE_RIGHT - SCOPE_LEFT}" height="{SCOPE_HEIGHT}"/></clipPath>
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
  .wave-line, .wave-glow {{ fill: none; stroke-linecap: round; stroke-linejoin: round; }}
  .wave-line {{ stroke: #d7eef5; stroke-width: 2.4; }}
  .wave-glow {{ stroke: #a1d0e1; stroke-opacity: .20; stroke-width: 6; }}
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
<text class="title" x="59" y="44">Contribution trace</text>
<text class="status" x="960" y="43" text-anchor="end">{status}</text>
<path class="baseline" d="M39 58H961"/>
<text class="panel-title" x="39" y="{READOUT_Y}">Activity waveform</text>
<rect x="{SCOPE_LEFT}" y="{SCOPE_TOP}" width="{SCOPE_RIGHT - SCOPE_LEFT}" height="{SCOPE_HEIGHT}" rx="4" fill="#13212a" stroke="#4a636e"/>
<rect x="{SCOPE_LEFT}" y="{SCOPE_TOP}" width="{SCOPE_RIGHT - SCOPE_LEFT}" height="{SCOPE_HEIGHT}" rx="4" fill="url(#grid)"/>
<path class="baseline" stroke-dasharray="3 4" d="M{SCOPE_LEFT} {SCOPE_CENTER}H{SCOPE_RIGHT}"/>
{graph}
<text class="axis" x="22" y="315.5" text-anchor="middle" transform="rotate(-90 22 315.5)">Relative amplitude</text>
<text class="axis" x="961" y="406" text-anchor="end">Time →</text>
</svg>
"""


if __name__ == "__main__":
    calendar = fetch_calendar(os.environ["PROFILE_LOGIN"], os.environ["GH_TOKEN"])
    Path("assets/contributions.svg").write_text(render(calendar), encoding="utf-8")
