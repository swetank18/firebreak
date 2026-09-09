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
PITCH = REPO / "www" / "index.html"
CONSOLE = REPO / "www" / "sim" / "index.html"


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
    m = re.search(r"const DATA = (\{.*?\});\n", console, re.S)
    assert m, "the console has no embedded scenario"
    d = json.loads(m.group(1))
    assert set(d["runs"]) == {"do_nothing", "firebreak", "human"}
    assert len(d["nodes"]) > 1000
    assert d["intervention"]["targets"] and d["human_action"]["targets"]
    # beat 5 has to still fail, and the console draws that comparison
    assert d["runs"]["human"]["summary"]["headline"] > d["runs"]["firebreak"]["summary"]["headline"]


def test_console_has_the_controls_the_runbook_promises(console):
    """Six keypresses, a rewindable clock, and three runs to switch between."""
    for probe, why in [
        ('id="beats"', "no beat bar"),
        ('id="track"', "no scrubbable timeline — the rewind demo needs one"),
        ('id="runs"', "no run selector"),
        ('id="play"', "no transport control"),
        ("e.key >= '1' && e.key <= '6'", "keys 1-6 do not drive the beats"),
        ('aria-label="Scrub the scenario clock"', "the timeline is not labelled for a screen reader"),
    ]:
        assert probe in console, why


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
