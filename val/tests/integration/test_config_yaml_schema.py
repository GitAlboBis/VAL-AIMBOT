"""Integration tests for the ``config.yaml`` schema.

Task 8.2 of the ``single-config-streamlining`` spec verifies that the
Config_File at the workspace root satisfies Requirements 7.1, 7.2, 7.3,
7.4, 7.5 and 7.9:

* 7.1 — ``general.architecture`` equals ``dual_pc``
* 7.2 — ``capture.backend`` equals ``capture_card``
* 7.3 — ``input.driver`` equals ``kmbox_net``
* 7.4 — ``general.primary_engine`` equals ``ai``
* 7.5 — ``input.kmbox_net`` contains non-empty ``ip``, ``port``, ``uuid``
  and ``use_encryption``
* 7.9 — diagnostic/legacy sections have been removed from the file
  (``hsv_engine``, ``memory_esp``, ``input.ib``,
  ``input.kmbox_serial``, ``input.makcu_serial``,
  ``input.makcu_socket``, ``input.efi``, ``general.exe_spoof``, and
  any key whose name contains ``spoof``, ``antidbg`` or
  ``threat_response`` as a substring)

The tests operate on the YAML structure only: they load the file with
``yaml.safe_load`` and assert structural invariants. No application code
is exercised.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Tuple

import pytest
import yaml


# --- Workspace layout -----------------------------------------------------

_WORKSPACE = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _WORKSPACE / "config.yaml"


# --- Fixtures -------------------------------------------------------------


@pytest.fixture(scope="module")
def config() -> dict:
    """Load ``config.yaml`` once per test module via ``yaml.safe_load``."""
    assert _CONFIG_PATH.is_file(), f"Config_File not found at {_CONFIG_PATH}"
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict), (
        "config.yaml must deserialize to a mapping at the top level"
    )
    return loaded


# --- Helpers --------------------------------------------------------------


_FORBIDDEN_SUBSTRINGS: Tuple[str, ...] = ("spoof", "antidbg", "threat_response")


def _iter_keys(node: Any, prefix: str = "") -> Iterator[Tuple[str, str]]:
    """Yield ``(dotted_path, key_name)`` pairs for every key in ``node``.

    Recurses into nested mappings and into mappings found inside lists.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            key_str = str(key)
            path = f"{prefix}.{key_str}" if prefix else key_str
            yield path, key_str
            yield from _iter_keys(value, path)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            path = f"{prefix}[{index}]"
            yield from _iter_keys(item, path)


# --- Tests: target values (Req 7.1-7.4) -----------------------------------


@pytest.mark.integration
class TestTargetConfigurationValues:
    """Assert the four Target_Configuration keys hold the expected values."""

    def test_general_architecture_is_dual_pc(self, config: dict) -> None:
        """Validates Requirement 7.1."""
        assert "general" in config, "config.yaml missing 'general' section"
        assert config["general"].get("architecture") == "dual_pc", (
            f"general.architecture must be 'dual_pc', "
            f"got {config['general'].get('architecture')!r}"
        )

    def test_capture_backend_is_capture_card(self, config: dict) -> None:
        """Validates Requirement 7.2."""
        assert "capture" in config, "config.yaml missing 'capture' section"
        assert config["capture"].get("backend") == "capture_card", (
            f"capture.backend must be 'capture_card', "
            f"got {config['capture'].get('backend')!r}"
        )

    def test_input_driver_is_kmbox_net(self, config: dict) -> None:
        """Validates Requirement 7.3."""
        assert "input" in config, "config.yaml missing 'input' section"
        assert config["input"].get("driver") == "kmbox_net", (
            f"input.driver must be 'kmbox_net', "
            f"got {config['input'].get('driver')!r}"
        )

    def test_general_primary_engine_is_ai(self, config: dict) -> None:
        """Validates Requirement 7.4."""
        assert "general" in config, "config.yaml missing 'general' section"
        assert config["general"].get("primary_engine") == "ai", (
            f"general.primary_engine must be 'ai', "
            f"got {config['general'].get('primary_engine')!r}"
        )


# --- Tests: kmbox_net section (Req 7.5) -----------------------------------


@pytest.mark.integration
class TestKmBoxNetSection:
    """Assert ``input.kmbox_net`` is present and fully populated."""

    _REQUIRED_KEYS: Tuple[str, ...] = ("ip", "port", "uuid", "use_encryption")

    def test_kmbox_net_section_exists(self, config: dict) -> None:
        """Validates Requirement 7.5 (presence)."""
        assert "input" in config, "config.yaml missing 'input' section"
        kmbox_net = config["input"].get("kmbox_net")
        assert isinstance(kmbox_net, dict), (
            "input.kmbox_net must exist and be a mapping; "
            f"got {type(kmbox_net).__name__}"
        )

    @pytest.mark.parametrize("key", _REQUIRED_KEYS)
    def test_kmbox_net_key_present_and_non_empty(
        self, config: dict, key: str
    ) -> None:
        """Validates Requirement 7.5 (each required key is non-empty)."""
        kmbox_net = config["input"]["kmbox_net"]
        assert key in kmbox_net, f"input.kmbox_net.{key} is missing"
        value = kmbox_net[key]
        # "non-empty": rejects None, empty string, empty collection; explicit
        # booleans (like use_encryption: true/false) are accepted as non-empty.
        assert value is not None, f"input.kmbox_net.{key} must not be null"
        if isinstance(value, (str, list, dict)):
            assert len(value) > 0, (
                f"input.kmbox_net.{key} must not be empty, got {value!r}"
            )


# --- Tests: legacy sections absent (Req 7.9) ------------------------------


@pytest.mark.integration
class TestLegacySectionsAbsent:
    """Assert every legacy section/sub-section has been removed."""

    @pytest.mark.parametrize("section", ["hsv_engine", "memory_esp"])
    def test_top_level_legacy_section_absent(
        self, config: dict, section: str
    ) -> None:
        """Validates Requirement 7.9 (top-level legacy sections)."""
        assert section not in config, (
            f"Legacy top-level section '{section}' must be removed from "
            f"config.yaml"
        )

    @pytest.mark.parametrize(
        "subsection",
        ["ib", "kmbox_serial", "makcu_serial", "makcu_socket", "efi"],
    )
    def test_input_legacy_subsection_absent(
        self, config: dict, subsection: str
    ) -> None:
        """Validates Requirement 7.9 (legacy sub-sections under ``input``)."""
        assert "input" in config, "config.yaml missing 'input' section"
        assert subsection not in config["input"], (
            f"Legacy sub-section 'input.{subsection}' must be removed from "
            f"config.yaml"
        )

    def test_general_exe_spoof_absent(self, config: dict) -> None:
        """Validates Requirement 7.9 (``general.exe_spoof`` removal)."""
        assert "general" in config, "config.yaml missing 'general' section"
        assert "exe_spoof" not in config["general"], (
            "Legacy key 'general.exe_spoof' must be removed from config.yaml"
        )

    @pytest.mark.parametrize("substring", _FORBIDDEN_SUBSTRINGS)
    def test_no_key_contains_forbidden_substring(
        self, config: dict, substring: str
    ) -> None:
        """Validates Requirement 7.9 (no key mentions spoof/antidbg/threat_response)."""
        offending = [
            path
            for path, key_name in _iter_keys(config)
            if substring in key_name
        ]
        assert not offending, (
            f"No key in config.yaml may contain the substring "
            f"{substring!r}; found offending keys: {offending}"
        )
