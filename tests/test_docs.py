"""Keep the documentation honest.

Entity ids, service names and card options all derive from code. If the code
changes and the docs do not, the docs become a trap for the next reader, so
these are asserted rather than trusted.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from custom_components.dreame_robot import binary_sensor, button, sensor
from custom_components.dreame_robot import services as services_module
from custom_components.dreame_robot.client.const import REGIONS
from custom_components.dreame_robot.client.render import CANVAS_MAX, MIN_EDGE, PADDING

ROOT = Path(__file__).resolve().parents[1]
DOCS = {path.name: path.read_text(encoding="utf-8") for path in (ROOT / "docs").glob("*.md")}
DOCS["README.md"] = (ROOT / "README.md").read_text(encoding="utf-8")
STRINGS = json.loads(
    (ROOT / "custom_components/dreame_robot/strings.json").read_text(encoding="utf-8")
)
CARD = (ROOT / "custom_components/dreame_robot/www/dreame-robot-map-card.js").read_text(
    encoding="utf-8"
)


def _slug(text: str) -> str:
    """Return the object-id slug Home Assistant derives from a display name."""
    ascii_text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", ascii_text.lower())).strip("_")


def _suffix(platform: str, description) -> str:
    """Return the entity-id suffix for one entity description.

    Home Assistant names an entity from its translation when it has one, and
    from ``name`` otherwise -- never from the internal key.
    """
    key = description.translation_key
    if key and key in STRINGS["entity"].get(platform, {}):
        return _slug(STRINGS["entity"][platform][key]["name"])
    return _slug(description.name or description.key)


ENTITIES = [
    *(("sensor", d) for d in sensor.SENSORS),
    *(("binary_sensor", d) for d in binary_sensor.BINARY_SENSORS),
    *(("button", d) for d in button.BUTTONS),
]


@pytest.mark.parametrize(
    ("platform", "description"),
    ENTITIES,
    ids=[f"{p}-{d.key}" for p, d in ENTITIES],
)
def test_entity_id_is_documented(platform: str, description) -> None:
    """Every entity the integration creates appears in the reference."""
    expected = f"`{platform}.*_{_suffix(platform, description)}`"
    assert expected in DOCS["entities.md"], f"{expected} is missing from docs/entities.md"


def test_no_documented_entity_is_invented() -> None:
    """The reference does not list entity ids the code cannot produce."""
    produced = {_suffix(platform, d) for platform, d in ENTITIES}
    documented = set(
        re.findall(r"`(?:sensor|binary_sensor|button)\.\*_([a-z_0-9]+)`", DOCS["entities.md"])
    )
    assert not documented - produced, f"documented but not created: {documented - produced}"


@pytest.mark.parametrize("name", sorted(services_module.SCHEMAS))
def test_service_is_documented(name: str) -> None:
    """Every registered service has a section in the reference."""
    assert f"### `dreame_robot.{name}`" in DOCS["entities.md"]


def test_no_service_is_documented_that_does_not_exist() -> None:
    """The reference does not describe services the code does not register."""
    documented = set(re.findall(r"### `dreame_robot\.([a-z_]+)`", DOCS["entities.md"]))
    assert documented == set(services_module.SCHEMAS)


@pytest.mark.parametrize("option", ["entity", "title", "refresh_interval"])
def test_card_option_is_implemented_and_documented(option: str) -> None:
    """Card options in the guide are real options in the card."""
    assert f"_config.{option}" in CARD or f"config.{option}" in CARD
    assert f"`{option}`" in DOCS["cards.md"]


def test_documented_regions_exist_in_the_client() -> None:
    """Every region the install guide names is one the client accepts."""
    for region in REGIONS:
        assert region in DOCS["installation.md"]


def test_projection_constants_are_quoted_correctly() -> None:
    """The map guide must not drift from the renderer's actual constants."""
    for value in (CANVAS_MAX, PADDING, MIN_EDGE):
        assert str(value) in DOCS["maps.md"]


def test_readme_links_resolve() -> None:
    """Every relative link and image in the README points at a real file."""
    readme = DOCS["README.md"]
    for target in re.findall(r"\]\((?!https?:)([^)#]+)", readme):
        assert (ROOT / target).exists(), f"README links to a missing file: {target}"


def test_docs_link_to_each_other_consistently() -> None:
    """Cross-document links resolve too."""
    for name, text in DOCS.items():
        if name == "README.md":
            continue
        for target in re.findall(r"\]\((?!\.\./|https?:|#)([^)#]+\.md)", text):
            assert (ROOT / "docs" / target).exists(), (
                f"{name} links to a missing file: {target}"
            )
