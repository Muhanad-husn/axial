"""The operator console itself -- the Streamlit script `axial console` runs.

Three screens, all of them read-only except one button: what is on the shelf
and an ingest that starts detached, a live run monitor, and the status
screen. It reads `data/` through `axial.runlog`/`axial.paths` and asks the
`axial` CLI everything else (`cli_bridge`); it imports no pass module.

**Live** here means a rerun loop, not `axial.runlog.follow_run`. `follow_run`
is a blocking generator built for a terminal tail; Streamlit's own tailing
mechanism is to re-run the script, and `load_run` (via `monitor.snapshot`) is
the same reader over the same files, re-read from byte zero each time. A run
directory is a few hundred lines, so there is nothing to save by tailing.

**Theme.** `.streamlit/config.toml` carries the mockup's palette in
Streamlit's own two-palette form and leaves `theme.base` unset, so an
operator who never touches the control gets whatever the browser asked for --
system, by default. `st.context.theme.type` is what the browser asked for;
the Light/Dark/System control overrides it for this session and, being a
keyed widget, survives every rerun. Serif (Newsreader) is only ever used for
prose -- the one place the console shows any, a run's own `summary.md`; the
interface is Helvetica and every id, pin and number is mono.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import streamlit as st

from axial.operator import cli_bridge, monitor
from axial.runlog import RunNotFoundError, format_duration

THEME_CHOICES = ("Light", "Dark", "System")
SCREENS = ("Run monitor", "Sources and ingest", "Status")

# The mockup's twelve theme values (frame 2d), verbatim in oklch, plus the
# three font stacks. Dark leaves `--bg` to `--lcolbg`, the darkest value the
# mockup declares -- the console is a full page, not a card on a canvas.
_LIGHT_VARS = """
  --bg: oklch(0.955 0.006 84);
  --panel: oklch(0.995 0.003 84);
  --sunken: oklch(0.925 0.005 84);
  --lcolbg: oklch(0.975 0.004 84);
  --barbg: oklch(0.915 0.005 84);
  --ink: oklch(0.24 0.012 80);
  --ink2: oklch(0.47 0.010 80);
  --ink3: oklch(0.65 0.008 80);
  --rule: oklch(0.895 0.006 80);
  --rule2: oklch(0.945 0.004 80);
  --stated: oklch(0.55 0.11 155);
  --concluded: oklch(0.55 0.11 255);
  --spec: oklch(0.55 0.11 55);
  --warnbg: oklch(0.55 0.11 55 / 0.07);
  --warnline: oklch(0.55 0.11 55 / 0.35);
"""

_DARK_VARS = """
  --bg: oklch(0.203 0.008 80);
  --panel: oklch(0.225 0.009 80);
  --sunken: oklch(0.267 0.009 80);
  --lcolbg: oklch(0.203 0.008 80);
  --barbg: oklch(0.305 0.008 80);
  --ink: oklch(0.930 0.007 80);
  --ink2: oklch(0.745 0.007 80);
  --ink3: oklch(0.570 0.007 80);
  --rule: oklch(0.330 0.008 80);
  --rule2: oklch(0.288 0.008 80);
  --stated: oklch(0.745 0.105 155);
  --concluded: oklch(0.745 0.105 255);
  --spec: oklch(0.775 0.105 65);
  --warnbg: oklch(0.775 0.105 65 / 0.10);
  --warnline: oklch(0.775 0.105 65 / 0.40);
"""

_CHROME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap');
:root {
  --sans: "Helvetica Neue", Helvetica, sans-serif;
  --serif: "Newsreader", Georgia, serif;
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
.stApp, [data-testid="stSidebar"] { background: var(--bg); color: var(--ink); }
.stApp, .stApp p, .stApp label { font-family: var(--sans); }
/* Serif is only ever for prose, never for the interface. `st.container(key=
   "run-summary")` is what puts `st-key-run-summary` on the DOM node. */
.st-key-run-summary, .st-key-run-summary p, .st-key-run-summary li,
.st-key-run-summary h1, .st-key-run-summary h2 {
  font-family: var(--serif); color: var(--ink);
}
code, pre, [data-testid="stMetricValue"] { font-family: var(--mono) !important; }
[data-testid="stMetricLabel"] {
  font: 9.5px var(--mono); letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink3);
}
.monbar {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 11px 18px; border: 1px solid var(--rule2); border-radius: 8px;
  background: var(--panel); margin-bottom: 14px;
}
.runname { font: 600 12px var(--mono); color: var(--ink); }
.live { font: 10px var(--mono); color: var(--stated); }
.dead { font: 10px var(--mono); color: var(--ink3); }
.dot {
  width: 7px; height: 7px; border-radius: 50%; background: var(--stated);
  display: inline-block; margin-right: 6px;
}
.passes { display: flex; flex-direction: column; gap: 13px; padding: 4px 0 10px; }
.pass { display: grid; grid-template-columns: 130px 1fr 150px; gap: 14px; align-items: center; }
.pname { font: 11.5px var(--mono); color: var(--ink2); }
.bar {
  display: block; height: 7px; border-radius: 4px; background: var(--barbg); overflow: hidden;
}
.fill { display: block; height: 100%; border-radius: 4px; background: var(--concluded); }
.fill.ok { background: var(--stated); }
[data-testid="stAlert"] {
  background: var(--warnbg) !important; border: 1px solid var(--warnline) !important;
  color: var(--ink) !important; border-radius: 7px;
}
"""


def resolve_theme(choice: str, browser_theme: str | None) -> str:
    """Which palette to paint: the operator's explicit choice when they made
    one, otherwise what the browser asked for, otherwise light."""
    if choice in ("Light", "Dark"):
        return choice.lower()
    return browser_theme if browser_theme in ("light", "dark") else "light"


def _browser_theme() -> str | None:
    theme = getattr(st.context, "theme", None)
    return getattr(theme, "type", None) if theme is not None else None


def _apply_theme(mode: str) -> None:
    variables = _DARK_VARS if mode == "dark" else _LIGHT_VARS
    st.html(f"<style>:root {{{variables}}}\n{_CHROME_CSS}</style>")


def _sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.markdown("### Axial")
        st.caption("operator console")
        screen = st.radio("Screen", SCREENS, key="screen", label_visibility="collapsed")
        st.divider()
        choice = st.segmented_control("Theme", THEME_CHOICES, default="System", key="theme_choice")
    return screen, choice or "System"


# ---------------------------------------------------------------------------
# Run monitor
# ---------------------------------------------------------------------------


def _headline_stats(snap: monitor.RunSnapshot) -> None:
    columns = st.columns(4)
    columns[0].metric("units of work", f"{snap.units:,}")
    columns[1].metric("model calls", f"{snap.model_calls:,}")
    columns[2].metric("spent", f"${snap.spend_usd:,.2f}" if snap.spend_usd is not None else "n/a")
    concurrency = (
        f"{snap.effective_concurrency:.1f}x" if snap.effective_concurrency is not None else "n/a"
    )
    columns[3].metric(
        f"effective concurrency{f' / {snap.workers}' if snap.workers else ''}", concurrency
    )


def _pass_bars(snap: monitor.RunSnapshot) -> None:
    if not snap.passes:
        st.caption("no pass has recorded anything yet")
        return
    rows = []
    for row in snap.passes:
        fraction = row.fraction
        width = f"{(fraction or 0) * 100:.0f}%"
        state = "ok" if fraction == 1.0 else ""
        if row.total:
            label = f"{row.settled} / {row.total}"
        else:
            label = f"{row.settled} recorded"
        if row.running:
            label += f" &middot; {row.running} running"
        if row.failed:
            label += f" &middot; {row.failed} failed"
        rows.append(
            f'<div class="pass"><span class="pname">{row.name}</span>'
            f'<span class="bar"><span class="fill {state}" style="width:{width}"></span></span>'
            f'<span class="pname" style="text-align:right">{label}</span></div>'
        )
    st.html(f'<div class="passes">{"".join(rows)}</div>')


def _quiet_band(snap: monitor.RunSnapshot) -> None:
    """Silence must read as *check this*, never as healthy -- so a live run
    always gets a band, and it always states how long it has been quiet
    against the cadence the run itself has been keeping."""
    quiet = snap.quiet
    if quiet is None:
        if snap.alive:
            st.info("Alive, but nothing logged yet. No cadence to judge the silence against.")
        return
    expected = (
        f"Expected one every ~{format_duration(quiet.expected_interval_sec)}."
        if quiet.expected_interval_sec is not None
        else "No cadence recorded yet."
    )
    silence = format_duration(quiet.quiet_sec)
    if quiet.overdue:
        opening = f"**Stalled: quiet {silence}, with nothing in flight.**"
    else:
        opening = f"**Quiet {silence}.** {quiet.in_flight} unit(s) still in flight."
    message = (
        f"{opening} Last event was {quiet.last_mark}. {expected} "
        "Silence is not health -- check the worker before assuming progress."
    )
    (st.warning if quiet.overdue else st.info)(message)


def _run_monitor() -> None:
    runs = monitor.recent_runs()
    if not runs:
        st.info("No runs recorded yet. Start one from Sources and ingest.")
        return

    labels = {f"{run.run_id}  --  {'alive' if run.alive else run.status}": run for run in runs}
    picked = st.selectbox("Run", list(labels), key="picked_run")
    run = labels[picked]

    try:
        snap = monitor.snapshot(run.run_dir)
    except RunNotFoundError:
        st.error(f"{run.run_id} is no longer readable.")
        return

    liveness = (
        '<span class="live"><span class="dot"></span>running</span>'
        if snap.alive
        else f'<span class="dead">{snap.status}</span>'
    )
    elapsed = format_duration(snap.elapsed_sec) if snap.elapsed_sec is not None else "--"
    st.html(
        f'<div class="monbar"><span class="runname">{snap.run_id}</span>'
        f"<span>{liveness} &middot; {elapsed}</span></div>"
    )

    _headline_stats(snap)
    _pass_bars(snap)
    _quiet_band(snap)

    if snap.failures:
        st.error(f"{snap.failures} unit(s) recorded a failure. `axial runs show {snap.run_id}`")

    st.code(snap.command, language=None)

    refresh = st.checkbox("Auto-refresh every 2s", key="auto_refresh")
    if refresh and snap.alive:
        time.sleep(2)
        st.rerun()


# ---------------------------------------------------------------------------
# Sources and ingest
# ---------------------------------------------------------------------------


def _sources() -> None:
    st.caption("`axial sources --check` -- free on the local backend: no download, no model call.")
    if st.button("Check the shelf", key="check_sources"):
        st.session_state["sources_report"] = cli_bridge.run_axial(["sources", "--check"])

    result = st.session_state.get("sources_report")
    if result is not None:
        if result.returncode != 0:
            st.error(result.stderr or "axial sources failed")
        rows = cli_bridge.parse_sources_report(result.stdout)
        if rows:
            counts: dict[str, int] = {}
            for row in rows:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            st.caption(" &middot; ".join(f"{count} {status}" for status, count in counts.items()))
            st.dataframe(rows, hide_index=True)
        else:
            st.caption("nothing on the shelf")

    st.divider()
    st.caption(
        "Ingest runs detached: it keeps going when this console, or the browser tab, closes."
    )
    if st.button("Ingest what is new or changed", key="start_ingest", type="primary"):
        pid, console_log = cli_bridge.launch_detached(["sources"])
        st.session_state["last_launch"] = (pid, str(console_log))

    launch = st.session_state.get("last_launch")
    if launch is not None:
        st.success(
            f"Ingest running detached as pid {launch[0]}. Console output: `{launch[1]}`. "
            "Watch it on the Run monitor screen."
        )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def _status() -> None:
    st.caption("`axial status` -- corpus counts, the live pin, and what is still pending.")
    if st.button("Read status", key="read_status"):
        st.session_state["status_report"] = cli_bridge.run_axial(["status"])

    result = st.session_state.get("status_report")
    if result is not None:
        if result.returncode != 0:
            st.error(result.stderr or "axial status failed")
        st.code(result.stdout or "(no output)", language=None)

    st.divider()
    st.markdown("**What the last run left behind**")
    runs = monitor.recent_runs(limit=1)
    if not runs:
        st.caption("no runs recorded")
        return
    snap = monitor.snapshot(runs[0].run_dir)
    st.caption(f"{snap.run_id} -- {'alive' if snap.alive else snap.status}")
    report = snap.report
    if report is None:
        st.caption("no report.json -- this run has not finished, or it was not a `axial run` pass")
        return
    columns = st.columns(4)
    columns[0].metric("ok", report.get("ok_count", 0))
    columns[1].metric("failed", report.get("fail_count", 0))
    columns[2].metric("skipped", report.get("skip_count", 0))
    columns[3].metric("outstanding", len(report.get("outstanding") or []))
    summary = runs[0].run_dir / "summary.md"
    if summary.is_file():
        with st.container(key="run-summary"):
            st.markdown(summary.read_text(encoding="utf-8"))


def main() -> None:
    st.set_page_config(page_title="Axial operator", layout="wide")
    screen, choice = _sidebar()
    st.session_state["resolved_theme"] = resolve_theme(choice, _browser_theme())
    _apply_theme(st.session_state["resolved_theme"])

    st.caption(f"read at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}")
    if screen == "Run monitor":
        _run_monitor()
    elif screen == "Sources and ingest":
        _sources()
    else:
        _status()


main()
