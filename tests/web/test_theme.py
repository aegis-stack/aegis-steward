"""Theming: theme x mode x finish, generated from one token source.

Three axes. ``theme`` is voice, shape and type, one file each under
``web_frontend/themes/`` (aegis: operational, steward: personal); ``mode``
is light or dark (or system, resolved client-side); ``finish`` is how
surfaces are lit (matte, lustre). ``tailwind.config.js`` combines them
into DaisyUI themes named ``<theme>-<mode>-<finish>``, every one at parity;
every color a template uses is a ``aegis-*`` name that reads DaisyUI's
variables, so nothing is defined twice. These tests keep that single
rebrand point single.
"""

import json
from pathlib import Path
import re
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    ChartColors,
)
from app.components.web_frontend.rendering import templates
from app.components.web_frontend.themes import (
    THEMES_DIR,
    Theme,
    Typeface,
    theme_named,
    themes,
)
from app.core.config import settings
from app.core.constants import CHART_RAMP
from tests.web.dom import one, select
from tests.web.node import run

WEB = Path("app/components/web_frontend")
INPUT_CSS = WEB / "static/input.css"
TAILWIND = Path("tailwind.config.js")
THEMES = tuple(themes())
MODES = ("dark", "light")
FINISHES = ("matte", "lustre")
DEFAULT = f"{settings.WEB_THEME}-dark-matte"
# The finish tokens: how a surface is lit. Matte sets every one to a no-op,
# so the classes that read them never need to know which theme is on.
FINISH = (
    "--aegis-sheen",
    "--aegis-edge",
    "--aegis-elevation",
    "--aegis-lift",
    "--aegis-glow",
    "--aegis-frost",
    "--aegis-float-alpha",
)
# The floating shadow is spelled once, in ``.floating``; a template that
# writes its own is a second finish the theme cannot reach.
SHADOW_RECIPE = re.compile(r"\bshadow-(?:sm|md|lg|xl|2xl)\b")
# The raised surface is spelled once, in ``.raised``.
RAISED_RECIPE = re.compile(
    r"bg-aegis-card border border-aegis-border rounded-lg"
    r"|rounded-lg border border-aegis-border bg-aegis-card"
)

HEX = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b(?![\w-])")
# Classes that hard-code what a theme decides: a literal color (looks
# right on one mode, wrong on the other) or a voice (uppercase micro-labels
# are aegis; steward speaks in sentence case). Use the token or the
# ``micro-label`` / ``caps`` classes instead.
THEME_BLIND = re.compile(
    r"\b(?:[\w-]+:)?(?:text|bg|border|ring|divide)-(?:white|black|gray-\d+|red-\d+)\b"
    r"|\b(?:uppercase|tracking-wider)\b"
)
# DaisyUI control classes are spelled once, in the form macros
# (``control`` and ``button_classes``); a template that writes them out
# is a second recipe waiting to drift.
CONTROL_RECIPE = re.compile(
    r"\b(?:btn|input|select|textarea|checkbox|radio)-(?:xs|sm|bordered|primary)\b"
    # The chosen-chip fill belongs to ``.chip`` in input.css, not a template.
    r"|\bpeer-checked:|\baria-\[pressed"
)
FORM_MACROS = WEB / "templates/components/macros/form.html"
# The template's chat, taken whole in the update: its markup keeps the
# template's DaisyUI controls and shadows until the kit is backported to it.
# ponytail: narrowed, not fixed; drop an entry once its file uses the kit.
TEMPLATE_CHAT = {
    WEB / "templates/components/chat_drawer.html",
    WEB / "templates/components/macros/chat.html",
    WEB / "templates/pages/overseer/ai/_voice_editor.html",
    WEB / "templates/partials/chat/surface.html",
    WEB / "templates/partials/chat/models.html",
}
# A class name assembled from parts (``btn-{{ size }}``) never reaches
# Tailwind's scanner, so it never compiles; spell every name in full.
BUILT_FROM_PARTS = re.compile(r'class="[^"]*[\w-]-{{')


# An ``aegis-*`` color as a utility names it: text-aegis-teal, bg-aegis-card/60.
AEGIS_COLOR = re.compile(
    r"\b(?:text|bg|border|ring|divide|fill|stroke|outline|from|via|to)-aegis-([a-z]+)\b"
)


def tailwind(path: str) -> Any:
    """``path`` of the Tailwind config (``.daisyui.themes``), with DaisyUI
    stubbed out: the config only names the plugin, it never calls it."""
    return run(
        "const M = require('module'); const load = M.prototype.require;"
        " M.prototype.require = function (id) {"
        " return id === 'daisyui' ? {} : load.apply(this, arguments); };"
        f" console.log(JSON.stringify(require('./tailwind.config.js'){path}))"
    )


def aegis_colors() -> set[str]:
    return set(tailwind(".theme.extend.colors.aegis"))


@pytest.fixture(scope="module")
def daisy_themes() -> dict[str, dict[str, str]]:
    return {
        name: body
        for entry in tailwind(".daisyui.themes")
        for name, body in entry.items()
    }


class TestThemeFiles:
    def test_a_theme_is_its_file(self) -> None:
        assert set(themes()) == {p.stem for p in THEMES_DIR.glob("*.json")}
        assert {"aegis", "steward"} <= set(themes())
        assert theme_named("aegis").label == "Aegis"

    def test_a_theme_that_is_not_there_names_the_ones_that_are(self) -> None:
        with pytest.raises(ValueError, match="aegis"):
            theme_named("parchment")


class TestMatrix:
    def test_every_theme_mode_finish_ships(
        self, daisy_themes: dict[str, dict[str, str]]
    ) -> None:
        assert set(daisy_themes) == {
            f"{t}-{m}-{f}" for t in THEMES for m in MODES for f in FINISHES
        }

    def test_all_generated_themes_share_tokens(
        self, daisy_themes: dict[str, dict[str, str]]
    ) -> None:
        keys = {frozenset(body) for body in daisy_themes.values()}
        assert len(keys) == 1
        assert {
            "primary",
            "base-100",
            "base-200",
            "base-300",
            "base-content",
            "neutral",
        } <= next(iter(keys))
        for body in daisy_themes.values():
            chart = [key for key in body if key.startswith("--aegis-chart-")]
            assert len(chart) == len(ChartColors.RAMP)
            assert body["--aegis-font-body"] and body["--aegis-font-display"]

    def test_shape_and_voice_follow_the_theme(
        self, daisy_themes: dict[str, dict[str, str]]
    ) -> None:
        for mode in MODES:
            aegis, steward = (
                daisy_themes[f"aegis-{mode}-matte"],
                daisy_themes[f"steward-{mode}-matte"],
            )
            assert aegis["--rounded-box"] != steward["--rounded-box"]
            assert aegis["--aegis-label-case"] == "uppercase"
            assert steward["--aegis-label-case"] == "none"

    def test_matte_leaves_the_finish_off(
        self, daisy_themes: dict[str, dict[str, str]]
    ) -> None:
        """Matte is how every theme has always looked: each finish token is
        the same no-op whatever the theme, so gloss is something people
        pick, never a change to what they already use."""
        for mode in MODES:
            aegis, steward = (
                daisy_themes[f"aegis-{mode}-matte"],
                daisy_themes[f"steward-{mode}-matte"],
            )
            assert {k: aegis[k] for k in FINISH} == {k: steward[k] for k in FINISH}
            assert aegis["--aegis-sheen"] == "none"
            assert aegis["--aegis-frost"] == "none"
            assert aegis["--aegis-float-alpha"] == "1"

    def test_lustre_lights_the_finish_and_nothing_else(
        self, daisy_themes: dict[str, dict[str, str]]
    ) -> None:
        """Lustre on any theme is that theme, lit: every finish token
        changes, and its palette, shape and voice do not."""
        for theme in THEMES:
            for mode in MODES:
                matte = daisy_themes[f"{theme}-{mode}-matte"]
                lustre = daisy_themes[f"{theme}-{mode}-lustre"]
                assert all(lustre[k] != matte[k] for k in FINISH), (theme, mode)
                rest = set(matte) - set(FINISH)
                assert {k: lustre[k] for k in rest} == {k: matte[k] for k in rest}
        # a white edge vanishes on a white card: light gets its own values
        assert (
            daisy_themes["aegis-light-lustre"]["--aegis-edge"]
            != (daisy_themes["aegis-dark-lustre"]["--aegis-edge"])
        )

    def test_surfaces_read_the_finish(self) -> None:
        css = INPUT_CSS.read_text()
        for cls in (".raised", ".floating"):
            assert cls in css
        for token in FINISH:
            assert f"var({token})" in css, token


class TestTokens:
    def test_only_a_card_you_can_click_lights_up_on_hover(self) -> None:
        """A teal border says "click me": ``hover-card`` goes on cards a
        click acts on, and a fold lights only while the pointer is on the
        header that opens it, never for passing over its body."""
        css = INPUT_CSS.read_text()
        assert ".hover-card:not(details):hover" in css
        assert ".hover-card:has(> summary:hover)" in css

    def test_the_ramp_is_one_size_everywhere_it_is_counted(self) -> None:
        """The theme's ramp, Flet's, the htmx charts' cycle and the colors a
        speaker or a logs page is given: one count, or the two UIs color
        the same thing apart."""
        charts = (WEB / "static/js/charts.js").read_text()
        cycle = re.search(r"const RAMP = (\d+);", charts)
        assert cycle and int(cycle[1]) == CHART_RAMP == len(ChartColors.RAMP)

    def test_tailwind_colors_read_daisyui_variables(self) -> None:
        """``bg-aegis-card`` and friends keep working; the values come from
        the active DaisyUI theme rather than a second table."""
        config = TAILWIND.read_text()
        assert (
            "const daisy = (name) => `oklch(var(--${name}) / <alpha-value>)`" in config
        )
        for name in ("bg", "card", "border", "text", "muted", "teal", "amber", "error"):
            assert re.search(rf'{name}: daisy\("[\w-]+"\)', config), name
        assert "[data-theme" not in INPUT_CSS.read_text()

    def test_every_aegis_color_in_use_is_defined(self) -> None:
        """An undefined one renders nothing in a template and fails the CSS
        build in an ``@apply``: ``aegis-accent`` did both, unnoticed until a
        page used the scheduler clock."""
        sources = [INPUT_CSS, *WEB.joinpath("templates").rglob("*.html")]
        used = {
            name for path in sources for name in AEGIS_COLOR.findall(path.read_text())
        }
        assert used - aegis_colors() == set()

    def test_shape_and_voice_tokens(self) -> None:
        config = TAILWIND.read_text()
        assert 'DEFAULT: "var(--rounded-btn)"' in config
        assert 'lg: "var(--rounded-box)"' in config
        assert 'display: "var(--aegis-font-display)"' in config
        css = INPUT_CSS.read_text()
        assert "font-size: var(--aegis-scale)" in css
        assert "font-family: var(--aegis-font-body)" in css
        assert ".micro-label" in css and "var(--aegis-label-case)" in css


class TestNoLiterals:
    @pytest.mark.parametrize(
        "path",
        sorted(p for p in WEB.rglob("*.html"))
        + sorted((WEB / "static/js").glob("*.js")),
        ids=lambda p: str(p.relative_to(WEB)),
    )
    def test_no_hex_outside_the_token_definitions(self, path: Path) -> None:
        source = path.read_text()
        # id selectors (#app-content) share the sigil; strip them first.
        source = re.sub(r"#[a-z][\w-]*[g-z_-][\w-]*", "", source)
        assert not HEX.search(source), HEX.search(source)

    @pytest.mark.parametrize(
        "path",
        sorted(WEB.rglob("*.html")),
        ids=lambda p: str(p.relative_to(WEB)),
    )
    def test_no_theme_blind_classes(self, path: Path) -> None:
        found = THEME_BLIND.findall(path.read_text())
        assert not found, found


class TestOneRecipe:
    @pytest.mark.parametrize(
        "path",
        sorted(WEB.rglob("*.html")),
        ids=lambda p: str(p.relative_to(WEB)),
    )
    def test_surfaces_come_from_the_surface_classes(self, path: Path) -> None:
        if path in TEMPLATE_CHAT:
            pytest.skip("the template's chat markup")
        source = path.read_text()
        found = SHADOW_RECIPE.findall(source) + RAISED_RECIPE.findall(source)
        assert not found, found

    @pytest.mark.parametrize(
        "path",
        sorted(p for p in WEB.rglob("*.html") if p != FORM_MACROS),
        ids=lambda p: str(p.relative_to(WEB)),
    )
    def test_controls_come_from_the_form_macros(self, path: Path) -> None:
        if path in TEMPLATE_CHAT:
            pytest.skip("the template's chat markup")
        found = CONTROL_RECIPE.findall(path.read_text())
        assert not found, found

    @pytest.mark.parametrize(
        "path",
        sorted(WEB.rglob("*.html")),
        ids=lambda p: str(p.relative_to(WEB)),
    )
    def test_no_class_name_is_built_from_parts(self, path: Path) -> None:
        found = BUILT_FROM_PARTS.findall(path.read_text())
        assert not found, found


class TestSwitching:
    def test_theme_script_runs_before_first_paint(self, shell: str) -> None:
        """A sync script in <head>, ahead of the stylesheet, applies the
        stored theme so a light-mode user never sees a dark flash."""
        page = shell
        head = one(page, "head")
        srcs = [
            (el.tag, el.get("src") or el.get("href") or "")
            for el in select(head, "script[src], link[rel=stylesheet]")
        ]
        theme = next(i for i, (_, s) in enumerate(srcs) if "js/theme" in s)
        stylesheet = next(i for i, (tag, _) in enumerate(srcs) if tag == "link")
        assert theme < stylesheet
        assert one(head, 'script[src*="js/theme"]').get("defer") is None

    def test_html_carries_the_default_theme(self, shell: str) -> None:
        page = shell
        assert one(page, "html").get("data-theme") == DEFAULT
        script = one(page, 'script[src*="js/theme"]')
        assert script.get("data-theme") == settings.WEB_THEME
        assert script.get("data-fixed") is None, "the viewer may switch"

    def test_choices_are_listed_once(self, shell: str) -> None:
        """The server owns the list: the sidebar renders it and <html>
        carries it for theme.js, so a new choice is one line in Python
        (a theme, one file) rather than one in each of three files."""
        html = one(shell, "html")
        choices = json.loads(html.get("data-appearance-choices") or "{}")
        assert choices["theme"] == list(THEMES)
        assert choices["mode"] == [*MODES, "system"]
        assert choices["finish"] == list(FINISHES)
        script = (WEB / "static/js/theme.js").read_text()
        assert "'steward'" not in script and "'lustre'" not in script

    def test_sidebar_offers_every_theme_and_mode(self, client: TestClient) -> None:
        aside = one(client.get("/overview").text, "aside#sidebar")
        assert one(aside, "button[data-appearance]").get("aria-label")
        assert {
            b.get("data-set-theme") for b in select(aside, "button[data-set-theme]")
        } == set(THEMES)
        assert {
            b.get("data-set-mode") for b in select(aside, "button[data-set-mode]")
        } == set(MODES) | {"system"}
        assert {
            b.get("data-set-finish") for b in select(aside, "button[data-set-finish]")
        } == set(FINISHES)

    def test_a_layout_may_fix_its_theme_and_load_its_type(self) -> None:
        """A layout that owns its theme wears it whatever the viewer chose,
        and its faces load before the stylesheet."""
        serif = Theme(
            name="parchment",
            shape={},
            type=Typeface(
                display="serif", body="serif", fonts="https://fonts.test/css2"
            ),
        )
        head = templates.env.from_string(
            '{% from "components/macros/layout.html" import appearance_head %}'
            "{{ appearance_head(theme, fixed=true) }}"
        ).render(theme=serif)
        script = one(head, 'script[src*="js/theme"]')
        assert (script.get("data-theme"), script.get("data-fixed")) == ("parchment", "")
        fonts = one(head, "link[data-theme-fonts]")
        assert fonts.get("href") == "https://fonts.test/css2"
        order = [
            el.get("src") or el.get("href")
            for el in select(head, "script[src], link[rel=stylesheet]")
        ]
        assert [("theme" in u, "fonts" in u, "app" in u) for u in order] == [
            (True, False, False),
            (False, True, False),
            (False, False, True),
        ], order


class TestHidden:
    def test_hidden_beats_a_display_utility(self) -> None:
        """``hidden`` is how every "nothing here yet" element hides, so it
        has to win against the ``block``/``flex`` class beside it. Without
        this the empty pending-changes banner reads "0 changes awaiting
        your review"."""
        css = INPUT_CSS.read_text()
        assert "[hidden] {" in css
        rule = css[css.index("[hidden] {") :]
        assert "display: none !important" in rule.split("}")[0]
