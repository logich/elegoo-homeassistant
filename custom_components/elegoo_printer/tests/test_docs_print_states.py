"""
Verify docs/SDCP_PRINT_STATES.md stays in sync with the status enums.

The document publishes state tables that users write automations against. The
enums are the source of truth, and firmware updates add states, so the tables
drift silently unless something checks them. These tests parse the markdown and
compare it against the code.

If one of these fails, the fix is normally to update the document, not the test.
"""

import json
import re
from pathlib import Path

import pytest

from custom_components.elegoo_printer.definitions import (
    _FDM_PRINT_STATUS_OPTIONS,
    _RESIN_PRINT_STATUS_OPTIONS,
)
from custom_components.elegoo_printer.sdcp.models.enums import (
    _FDM_PRINT_STATUS_CODES,
    ElegooMachineStatus,
    ElegooPrintStatus,
)

DOC_PATH = Path(__file__).parents[3] / "docs" / "SDCP_PRINT_STATES.md"

# States the document explicitly documents as unreachable. Keeping this here
# rather than deriving it means adding an unreachable state is a deliberate act
# that shows up in review.
RESIN_UNREACHABLE = {"printing_recovery"}
FDM_UNREACHABLE = {"recovery", "printing_recovery", "loading", "unrecognized"}


def _read_doc() -> str:
    assert DOC_PATH.is_file(), f"missing doc: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def _extract_table(doc: str, marker: str) -> list[tuple[str, str]]:
    """
    Pull (first column, ha_state) pairs out of a delimited markdown table.

    Tables are fenced by `<!-- <marker>:start -->` / `<!-- <marker>:end -->` so
    surrounding prose can change freely without breaking the parse.
    """
    block = re.search(
        rf"<!--\s*{re.escape(marker)}:start\s*-->(.*?)<!--\s*{re.escape(marker)}:end\s*-->",
        doc,
        re.DOTALL,
    )
    assert block, f"could not find table block {marker!r} in {DOC_PATH.name}"

    rows: list[tuple[str, str]] = []
    for raw_line in block.group(1).splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0].lower() in {"wire value", "wire code", "value"}:
            continue  # header
        if set(cells[0]) <= {"-", ":"}:
            continue  # separator
        code, state = cells[0], cells[1]
        assert state.startswith("`"), f"{marker}: HA state {state!r} needs backticks"
        assert state.endswith("`"), f"{marker}: HA state {state!r} needs backticks"
        rows.append((code, state.strip("`")))

    assert rows, f"table {marker!r} parsed to zero rows"
    return rows


@pytest.fixture(scope="module")
def doc() -> str:
    """Return the raw markdown of the states document."""
    return _read_doc()


def test_ha_state_strings_are_lowercased_member_names() -> None:
    """
    The documented mapping rule must match how definitions.py builds options.

    The doc tells users the HA state is always the enum member name lowercased.
    That claim only holds while the option lists are built that way.
    """
    assert [s.name.lower() for s in ElegooPrintStatus] == _FDM_PRINT_STATUS_OPTIONS

    member_names = {s.name.lower() for s in ElegooPrintStatus}
    unbacked = [o for o in _RESIN_PRINT_STATUS_OPTIONS if o not in member_names]
    assert not unbacked, f"resin options not backed by an enum member name: {unbacked}"
    assert all(o == o.lower() for o in _RESIN_PRINT_STATUS_OPTIONS)


def test_machine_status_table_matches_enum(doc: str) -> None:
    """Every ElegooMachineStatus member appears exactly once, with its value."""
    rows = _extract_table(doc, "machine-status-table")
    documented = {state: int(code) for code, state in rows}
    expected = {m.name.lower(): m.value for m in ElegooMachineStatus}

    assert documented == expected, (
        "machine status table is out of sync with ElegooMachineStatus.\n"
        f"  documented but not in enum: {sorted(set(documented) - set(expected))}\n"
        f"  in enum but not documented: {sorted(set(expected) - set(documented))}"
    )
    assert len(rows) == len(documented), "duplicate rows in machine status table"


def test_resin_print_status_table_matches_options(doc: str) -> None:
    """The resin table matches the options list the resin sensor advertises."""
    rows = _extract_table(doc, "resin-print-status-table")
    documented = {state: int(code) for code, state in rows}

    assert set(documented) == set(_RESIN_PRINT_STATUS_OPTIONS), (
        "resin print status table is out of sync with _RESIN_PRINT_STATUS_OPTIONS.\n"
        f"  documented but not advertised: "
        f"{sorted(set(documented) - set(_RESIN_PRINT_STATUS_OPTIONS))}\n"
        f"  advertised but not documented: "
        f"{sorted(set(_RESIN_PRINT_STATUS_OPTIONS) - set(documented))}"
    )

    # The value column must be the enum member value.
    for state, code in documented.items():
        member = ElegooPrintStatus[state.upper()]
        assert code == member.value, (
            f"resin table lists {state!r} as {code}, "
            f"enum member value is {member.value}"
        )


def test_fdm_print_status_table_matches_wire_codes(doc: str) -> None:
    """The FDM table matches _FDM_PRINT_STATUS_CODES exactly, by wire code."""
    rows = _extract_table(doc, "fdm-print-status-table")
    documented = {int(code): state for code, state in rows}
    expected = {code: m.name.lower() for code, m in _FDM_PRINT_STATUS_CODES.items()}

    assert documented == expected, (
        "FDM print status table is out of sync with _FDM_PRINT_STATUS_CODES.\n"
        f"  documented but not in code table: "
        f"{sorted(set(documented) - set(expected))}\n"
        f"  in code table but not documented: "
        f"{sorted(set(expected) - set(documented))}"
    )


def test_fdm_table_uses_wire_codes_not_member_values(doc: str) -> None:
    """
    Guard the +100 offset: FDM-only states must be listed by wire code.

    Documenting the member value here would be a plausible mistake and would
    send integrators looking for a code the printer never sends.
    """
    rows = _extract_table(doc, "fdm-print-status-table")
    for code_str, state in rows:
        member = ElegooPrintStatus[state.upper()]
        code = int(code_str)
        if member.value >= 100:
            assert code == member.value - 100, (
                f"FDM-only state {state!r} should be listed by wire code "
                f"{member.value - 100}, not member value {member.value}"
            )


def test_documented_unreachable_states_are_still_unreachable() -> None:
    """
    The 'States you will never see' section must stay true.

    Resin: from_int rewrites code 13 to PRINTING, so printing_recovery can
    never reach the sensor. FDM: these are advertised via the generated options
    list but have no wire code.
    """
    assert ElegooPrintStatus.from_int(ElegooPrintStatus.PRINTING_RECOVERY.value) is (
        ElegooPrintStatus.PRINTING
    ), "resin from_int no longer rewrites printing_recovery; update the doc"

    for code in (18, 19, 21):
        assert ElegooPrintStatus.from_int(code) is ElegooPrintStatus.LOADING, (
            f"resin code {code} no longer collapses to loading; update the doc"
        )

    reachable_fdm = {m.name.lower() for m in _FDM_PRINT_STATUS_CODES.values()}
    for state in FDM_UNREACHABLE - {"unrecognized"}:
        assert state not in reachable_fdm, (
            f"FDM state {state!r} is now reachable; update the doc"
        )


def test_unreachable_states_are_documented(doc: str) -> None:
    """Anything advertised but unreachable must be called out in the doc."""
    advertised_resin = set(_RESIN_PRINT_STATUS_OPTIONS)
    reachable_resin = {
        m.name.lower()
        for m in (ElegooPrintStatus.from_int(c) for c in range(256))
        if m is not None
    }
    unreachable = advertised_resin - reachable_resin

    assert unreachable == RESIN_UNREACHABLE, (
        "the set of unreachable resin states changed.\n"
        f"  now unreachable: {sorted(unreachable)}\n"
        f"  doc claims:      {sorted(RESIN_UNREACHABLE)}"
    )

    parts = doc.split("## States you will never see", 1)
    assert len(parts) == 2, "doc is missing the 'States you will never see' section"
    section = parts[1]

    # Scope the search to the resin subsection. Searching the whole section
    # would pass on the FDM paragraph merely mentioning the same state name.
    assert "**Resin:**" in section, (
        "unreachable-states section lost its Resin subsection"
    )
    resin_part = section.split("**Resin:**", 1)[1].split("**FDM:**", 1)[0]

    for state in unreachable:
        assert state in resin_part, (
            f"unreachable resin state {state!r} is not documented under '**Resin:**'"
        )


def test_fdm_unknown_code_surfaces_as_unrecognized() -> None:
    """Documented FDM fallback behaviour: never None, always a visible state."""
    assert ElegooPrintStatus.from_fdm_int(3) is ElegooPrintStatus.UNRECOGNIZED
    assert ElegooPrintStatus.from_fdm_int(9999) is ElegooPrintStatus.UNRECOGNIZED


def test_cc2_unmapped_substatus_falls_back_to_idle() -> None:
    """
    CC2 does *not* get the UNRECOGNIZED guarantee — the doc says so.

    The CC2 mapper defaults unmapped sub-status codes to IDLE, so a CC2 printer
    can read `idle` while mid-operation. If this ever changes to UNRECOGNIZED,
    the "Centauri Carbon 2 (CC2) is different" section becomes wrong.
    """
    from custom_components.elegoo_printer.cc2.models import (  # noqa: PLC0415
        CC2StatusMapper,
    )

    assert (
        CC2StatusMapper.PRINT_STATUS_MAP.get(999_999, ElegooPrintStatus.IDLE)
        is ElegooPrintStatus.IDLE
    )
    reachable = set(CC2StatusMapper.PRINT_STATUS_MAP.values())
    fdm_only = {m for m in ElegooPrintStatus if m.value >= 100}
    assert not (reachable & fdm_only), (
        "CC2 now produces FDM-only states; the doc claims it never does: "
        f"{sorted(m.name.lower() for m in reachable & fdm_only)}"
    )


@pytest.mark.parametrize(
    ("translation_key", "enum"),
    [("print_status", ElegooPrintStatus), ("current_status", ElegooMachineStatus)],
)
def test_every_locale_translates_every_state(translation_key: str, enum: type) -> None:
    """
    All 18 locales must carry a state block covering the whole enum.

    Adding an enum member means editing every translation file. Nothing else
    enforces that, so a new state would otherwise ship showing users a raw
    slug in whichever locales were missed.
    """
    locale_dir = Path(__file__).parents[1] / "translations"
    locales = sorted(locale_dir.glob("*.json"))
    assert locales, f"no translation files found in {locale_dir}"

    expected = {m.name.lower() for m in enum}
    problems: list[str] = []

    for path in locales:
        states = (
            json.loads(path.read_text(encoding="utf-8"))
            .get("entity", {})
            .get("sensor", {})
            .get(translation_key, {})
            .get("state")
        )
        if states is None:
            problems.append(f"{path.name}: no '{translation_key}.state' block")
            continue
        if missing := sorted(expected - set(states)):
            problems.append(f"{path.name}: missing {missing}")
        if extra := sorted(set(states) - expected):
            problems.append(f"{path.name}: unknown keys {extra}")

    assert not problems, "translation drift:\n  " + "\n  ".join(problems)


def test_state_strings_relied_on_by_shipped_docs_are_stable() -> None:
    """
    SPOOLMAN.md ships automations keyed on these exact strings.

    Renaming an enum member silently breaks every user config copied from that
    document, so these are effectively public API.
    """
    for state in ("complete", "printing", "paused"):
        assert state in {m.name.lower() for m in ElegooPrintStatus}, (
            f"print_status {state!r} is referenced by SPOOLMAN.md automations"
        )
    assert "loading_unloading" in {m.name.lower() for m in ElegooMachineStatus}
