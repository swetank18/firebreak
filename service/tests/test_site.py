"""The two deployed pages, and the promises they make.

`www/index.html` is the write-up; `www/sim/index.html` is the simulation
console. They are committed rather than built in CI, because their numbers come
from `eval/results/`, which takes tens of minutes to regenerate. So the thing to
guard is that what is committed still matches its inputs and still contains what
it claims to.

`EXECUTION.md` non-negotiable 4 — every number is produced by a script — is why
the placeholder check matters: an unfilled `__TOKEN__` reaching the deployed
page would be a number that was never generated.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
# the console assigns onto window so the tab module can read it
DATA_RE = r"(?:const|window\.)\s*DATA\s*=\s*(\{.*?\});\n"
PITCH = REPO / "www" / "index.html"
CONSOLE = REPO / "www" / "sim" / "index.html"          # 3D
CONSOLE_APP = REPO / "www" / "sim" / "app.js"
CONSOLE_2D = REPO / "www" / "sim" / "2d" / "index.html"  # the fallback
THREE = REPO / "www" / "sim" / "vendor" / "three.min.js"


@pytest.fixture(scope="module")
def pitch() -> str:
    if not PITCH.exists():
        pytest.fail("www/index.html missing. Run scripts/build_site.py.")
    return PITCH.read_text()


@pytest.fixture(scope="module")
def console() -> str:
    if not CONSOLE.exists():
        pytest.fail("www/sim/index.html missing. Run scripts/build_site.py.")
    return CONSOLE.read_text()


@pytest.fixture(scope="module")
def app() -> str:
    if not CONSOLE_APP.exists():
        pytest.fail("www/sim/app.js missing. Run scripts/build_site.py.")
    return CONSOLE_APP.read_text()


@pytest.fixture(scope="module")
def console2d() -> str:
    if not CONSOLE_2D.exists():
        pytest.fail("www/sim/2d/index.html missing. Run scripts/build_site.py.")
    return CONSOLE_2D.read_text()


def test_both_pages_are_whole_documents(pitch, console):
    for name, html in (("pitch", pitch), ("console", console)):
        assert html.lstrip().startswith("<!doctype html>"), f"{name} has no doctype"
        assert "</head>" in html and "</body>" in html, f"{name} is not a complete document"


def test_no_unfilled_placeholders_reach_the_deployed_pages(pitch, console):
    for name, html in (("pitch", pitch), ("console", console)):
        left = set(re.findall(r"__[A-Z][A-Z_]+__", html))
        assert not left, f"{name} still contains template placeholders: {sorted(left)}"


def test_nojekyll_is_present():
    """Without it GitHub Pages drops paths beginning with an underscore."""
    assert (REPO / "www" / ".nojekyll").exists(), "www/.nojekyll missing"


def test_the_console_is_a_separate_url(pitch, console):
    assert CONSOLE.parent.name == "sim"
    assert 'href="sim/"' in pitch, "the write-up does not link to the console"
    assert 'href="../"' in console, "the console does not link back"


def test_console_carries_all_three_runs(console):
    m = re.search(DATA_RE, console, re.S)
    assert m, "the console has no embedded scenario"
    d = json.loads(m.group(1))
    assert set(d["runs"]) == {"do_nothing", "firebreak", "human"}
    assert len(d["nodes"]) > 1000
    assert d["intervention"]["targets"] and d["human_action"]["targets"]
    # beat 5 has to still fail, and the console draws that comparison
    assert d["runs"]["human"]["summary"]["headline"] > d["runs"]["firebreak"]["summary"]["headline"]


def test_console_has_the_controls_the_runbook_promises(console, app):
    """Six keypresses, a rewindable clock, and three runs to switch between."""
    for probe, why in [
        ('id="beats"', "no beat bar"),
        ('id="track"', "no scrubbable timeline — the rewind demo needs one"),
        ('id="runs"', "no run selector"),
        ('id="play"', "no transport control"),
        ('aria-label="Scrub the scenario clock"', "the timeline is not labelled for a screen reader"),
    ]:
        assert probe in console, why
    assert "e.key >= '1' && e.key <= '6'" in app, "keys 1-6 do not drive the beats"


def test_the_3d_view_runs_offline():
    """EXECUTION.md: offline, no network, no live model call.

    three.js is vendored into the repo rather than pulled from a CDN, because a
    venue's wifi is not part of the demo. If this file goes missing the console
    silently falls back to the no-WebGL panel and the demo is a dead canvas.
    """
    assert THREE.exists(), "www/sim/vendor/three.min.js missing — the 3D view needs it"
    assert THREE.stat().st_size > 100_000
    assert 'src="vendor/three.min.js"' in CONSOLE.read_text(), (
        "the console does not load the vendored three.js, so it depends on a network"
    )


def test_the_2d_fallback_exists_and_reads_the_same_scenario(console2d, console):
    """EXECUTION.md non-negotiable 6: a 2D fallback exists, on the identical schema.

    If WebGL is unavailable on the venue projector, the same six keys have to
    work. Both pages are generated from one exported scenario, so they cannot
    disagree about what happened.
    """
    def payload(html: str) -> dict:
        return json.loads(re.search(DATA_RE, html, re.S).group(1))

    a, b = payload(console), payload(console2d)
    assert a["seed"] == b["seed"]
    assert a["runs"]["do_nothing"]["summary"] == b["runs"]["do_nothing"]["summary"]
    assert 'href="2d/"' in console, "the 3D console does not offer the fallback"
    assert "webgl" in console.lower(), "no WebGL fallback message"


def test_the_flood_is_the_hazard_field_not_an_animation(console):
    """The water level shown is what the engine used to stress the assets."""
    d = json.loads(re.search(DATA_RE, console, re.S).group(1))
    flood = d.get("flood")
    assert flood, "no flood field exported — the water would be decoration"
    assert len(flood["level"]) > 20 and flood["peak"] > 0
    assert max(flood["level"]) == pytest.approx(flood["peak"], rel=1e-6)
    # it is a front: it rises and it recedes
    assert flood["level"][0] < flood["peak"] and flood["level"][-1] < flood["peak"]
    # every asset carries the elevation the flood was compared against
    assert all("e" in n for n in d["nodes"])


def test_the_renderer_computes_no_simulation_numbers(pitch, console):
    """`EXECUTION.md` non-negotiable 6: the renderer replays, it never computes.

    The pitch page used to show `person_hours * elapsed_fraction`, inventing a
    figure the simulation never produced. Counting events that have already
    happened is reading the file; scaling a total by elapsed time is not.
    """
    for name, html in (("pitch", pitch), ("console", console)):
        assert "person_hours*frac" not in html.replace(" ", ""), (
            f"{name} interpolates person-hours, which the simulation never reported"
        )


def test_console_has_the_five_specified_tabs(console, app):
    """ui/ spec: a 6-component core screen plus four dedicated deep-dive tabs."""
    for probe in ('id="tab1"', 'id="tab2"', 'id="tab3"', 'id="tab4"', 'id="tab5"', 'id="tabs"'):
        assert probe in console, f"missing {probe}"
    for probe in ("Hospital lifelines", "Action plan", "Causal chain", "Benchmark lab"):
        assert probe in app, f"tab '{probe}' is not built"


def test_benchmark_tab_reads_the_real_ablation(console):
    """The spec's mockups carry illustrative arm numbers that contradict what we
    measured. The tab must render eval/results/, not the mockup."""
    m = re.search(r"window\.EVIDENCE = (\{.*?\});\n", console, re.S)
    assert m, "no evidence payload injected into the console"
    ev = json.loads(m.group(1))
    arms = {t["arm"]: t for t in ev["arms"]}
    assert {"A0", "AR", "A1", "A2", "A3", "A4", "A6"} <= set(arms)
    # the measured result, whichever way it went
    for arm in ("A3", "A4"):
        assert arms[arm]["p_holm"] is not None
    assert ev["h1"]["anomaly"] < 0.60 and ev["h2"]["rel"] is not None
    assert arms["A6"]["oracle_captured_pct"] == 100.0


def test_the_memorandum_states_its_own_confidence(app):
    """A directive that hides that its selection layer is unproven is not honest."""
    assert "not distinguishable from" in app
    assert "No model produced this text" in app or "no language model" in app.lower()


OPS = REPO / "www" / "ops" / "index.html"
OPS_APP = REPO / "www" / "ops" / "ops.js"
OPS_INDEX = REPO / "www" / "ops" / "data" / "index.json"


def test_operator_dashboard_controls_a_scenario_matrix():
    """The consoles replay one scenario. The dashboard picks one and drives it."""
    for f in (OPS, OPS_APP, OPS_INDEX):
        assert f.exists(), f"{f.name} missing. Run scripts/export_matrix.py, then build_site.py."
    idx = json.loads(OPS_INDEX.read_text())
    assert len(idx["scenarios"]) >= 8, "too thin a matrix to be worth controlling"
    hazards = {s["hazard"] for s in idx["scenarios"]}
    assert len(hazards) >= 3, f"only {hazards} — an operator should be able to change the hazard"
    for s in idx["scenarios"]:
        assert (REPO / "www" / "ops" / "data" / f"{s['key']}.json").exists()


def test_operator_dashboard_ranks_by_danger_and_can_be_judged_on_it():
    app = OPS_APP.read_text()
    for probe, why in [
        ("sortBy === 'br'", "no danger ranking"),
        ("hindsight", "no way to reveal which alarms actually mattered"),
        ("Dispatch", "an operator console you cannot act in is a slideshow"),
        ("decided.push", "decisions are not logged"),
    ]:
        assert probe in app, why


def test_the_alert_outcome_is_exported_not_inferred_in_the_browser():
    """`h` is ground truth from true_chains, computed once at export."""
    key = json.loads(OPS_INDEX.read_text())["scenarios"][0]["key"]
    sc = json.loads((REPO / "www" / "ops" / "data" / f"{key}.json").read_text())
    tl = sc["runs"]["do_nothing"]["timeline"]
    assert tl and all("h" in r and "br" in r and "s" in r for r in tl)


def test_a_zero_deadline_is_not_shown_as_an_expiry():
    """Zero means the solver could not establish one. Saying EXPIRED there is
    the system claiming a certainty it does not have."""
    app = OPS_APP.read_text()
    assert "hasDeadline" in app and "no deadline established" in app
