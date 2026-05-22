"""
Integration tests for ``config.load_config`` end-to-end against the
``input.kmbox_net.*`` block (KmBox Net Integration spec, task 2.2).

These tests exercise the full loader pipeline — file read → YAML parse →
default application → :func:`utils.validation.validate_target_configuration`
→ :func:`utils.validation.validate_kmbox_net_config` — through the public
``config.load_config()`` entry point. Per-validator unit tests live in
``tests/input/test_kmbox_config_validation.py`` (Property 6); per-loader I/O
tests live in ``tests/config/test_config_kmbox_io.py`` (Req 3.11). This
file is the integration glue between them: it confirms the validator is
actually invoked from ``load_config`` (Req 3.1) and that a malformed key
on disk surfaces as a ``ConfigException`` whose message names the offending
dotted key (Req 3.7-3.10).

Each test points :data:`config._CONFIG_FILE` at a per-test artefact under
``tmp_path`` via :class:`pytest.MonkeyPatch`, mirroring the pattern in
``test_config_kmbox_io.py`` so the suite is fully hermetic and never reads
or writes the workspace's live ``config.yaml``.

Validates: Requirements 3.1, 3.11
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

import config
from exceptions import ConfigException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_valid_config() -> Dict[str, Any]:
    """Return the smallest dict that satisfies Target_Configuration + Req 3.

    The four ``TARGET_CONFIGURATION`` keys must be present (or default-applied
    by the loader) and the ``input.kmbox_net`` block must contain the four
    keys named in Req 3.1 with values that pass
    :func:`utils.validation.validate_kmbox_net_config`.
    """
    return {
        "general": {
            "architecture": "dual_pc",
            "primary_engine": "ai",
        },
        "capture": {
            "backend": "capture_card",
        },
        "input": {
            "driver": "kmbox_net",
            "kmbox_net": {
                "ip": "192.168.2.188",
                "port": "6234",
                "uuid": "00000000-0000-0000-0000-000000000000",
                "use_encryption": True,
            },
        },
    }


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True, allow_unicode=True)


def _point_loader_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    """Redirect :data:`config._CONFIG_FILE` to ``path`` for the test."""
    monkeypatch.setattr(config, "_CONFIG_FILE", str(path))


def _config_with_kmbox_value(key: str, value: Any) -> Dict[str, Any]:
    """Build a config dict with ``input.kmbox_net.<key>`` overridden."""
    cfg = _minimal_valid_config()
    cfg["input"]["kmbox_net"][key] = value
    return cfg


def _config_without_kmbox_value(key: str) -> Dict[str, Any]:
    """Build a config dict with ``input.kmbox_net.<key>`` removed."""
    cfg = _minimal_valid_config()
    del cfg["input"]["kmbox_net"][key]
    return cfg


# ---------------------------------------------------------------------------
# Req 3.1 — happy-path: load_config exposes the four kmbox_net keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadConfigExposesKmboxKeys:
    """``load_config`` returns the four ``input.kmbox_net.*`` keys with the
    expected types when given a minimal valid ``config.yaml``."""

    def test_load_config_returns_all_four_kmbox_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All four ``input.kmbox_net.*`` keys are present in the loaded dict (Req 3.1)."""
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, _minimal_valid_config())

        _point_loader_at(monkeypatch, config_path)

        loaded = config.load_config()

        kmbox_section = loaded.get("input", {}).get("kmbox_net")
        assert isinstance(kmbox_section, dict), (
            f"Expected input.kmbox_net to be a mapping, got "
            f"{type(kmbox_section).__name__}"
        )

        for key in ("ip", "port", "uuid", "use_encryption"):
            assert key in kmbox_section, (
                f"input.kmbox_net.{key} missing from loaded config"
            )

    def test_load_config_kmbox_keys_have_expected_types(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The four ``input.kmbox_net.*`` keys round-trip with the types Req 3.2-3.5 require."""
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, _minimal_valid_config())

        _point_loader_at(monkeypatch, config_path)

        loaded = config.load_config()
        kmbox_section = loaded["input"]["kmbox_net"]

        # Req 3.2 — ip is a string of four dotted decimal octets.
        assert isinstance(kmbox_section["ip"], str)
        # Req 3.3 — port is a decimal-digit string.
        assert isinstance(kmbox_section["port"], str)
        # Req 3.4 — uuid is a non-empty string.
        assert isinstance(kmbox_section["uuid"], str)
        # Req 3.5 — use_encryption is a strict bool. ``bool`` is a subclass
        # of ``int`` so the check is explicit to mirror the validator.
        assert isinstance(kmbox_section["use_encryption"], bool)

    def test_load_config_kmbox_values_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The four ``input.kmbox_net.*`` values survive ``load_config`` byte-equal."""
        expected = _minimal_valid_config()
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, expected)

        _point_loader_at(monkeypatch, config_path)

        loaded = config.load_config()
        kmbox_section = loaded["input"]["kmbox_net"]
        expected_kmbox = expected["input"]["kmbox_net"]

        assert kmbox_section["ip"] == expected_kmbox["ip"]
        assert kmbox_section["port"] == expected_kmbox["port"]
        assert kmbox_section["uuid"] == expected_kmbox["uuid"]
        assert kmbox_section["use_encryption"] is expected_kmbox["use_encryption"]


# ---------------------------------------------------------------------------
# Req 3.7-3.10 — malformed kmbox_net keys raise ConfigException naming the key
# ---------------------------------------------------------------------------
#
# One parameterized case per ``input.kmbox_net.*`` key, plus a few edge-case
# variants per key to exercise distinct rejection branches in the validator.
# Each case mutates a single leaf and asserts ``ConfigException`` carries the
# dotted key in the message text. The dotted key MUST appear so operators
# can grep the log line directly to the offending ``config.yaml`` value.


_MALFORMED_KMBOX_CASES = [
    # ---- input.kmbox_net.ip (Req 3.7) ----
    pytest.param(
        "ip", "256.0.0.1", "input.kmbox_net.ip",
        id="ip-octet-out-of-range",
    ),
    pytest.param(
        "ip", "192.168.1", "input.kmbox_net.ip",
        id="ip-too-few-octets",
    ),
    pytest.param(
        "ip", "192.168.1.1.1", "input.kmbox_net.ip",
        id="ip-too-many-octets",
    ),
    pytest.param(
        "ip", "abc.def.ghi.jkl", "input.kmbox_net.ip",
        id="ip-non-numeric-octets",
    ),
    pytest.param(
        "ip", 12345, "input.kmbox_net.ip",
        id="ip-not-a-string",
    ),

    # ---- input.kmbox_net.port (Req 3.8) ----
    pytest.param(
        "port", "0", "input.kmbox_net.port",
        id="port-zero",
    ),
    pytest.param(
        "port", "65536", "input.kmbox_net.port",
        id="port-above-max",
    ),
    pytest.param(
        "port", "not_a_port", "input.kmbox_net.port",
        id="port-non-digit",
    ),
    pytest.param(
        "port", 6234, "input.kmbox_net.port",
        id="port-not-a-string",
    ),

    # ---- input.kmbox_net.uuid (Req 3.9) ----
    pytest.param(
        "uuid", "", "input.kmbox_net.uuid",
        id="uuid-empty-string",
    ),
    pytest.param(
        "uuid", "x" * 65, "input.kmbox_net.uuid",
        id="uuid-too-long",
    ),
    pytest.param(
        "uuid", 42, "input.kmbox_net.uuid",
        id="uuid-not-a-string",
    ),

    # ---- input.kmbox_net.use_encryption (Req 3.10) ----
    # ``bool`` is a subclass of ``int``; ``0`` and ``1`` must be rejected as
    # non-bool by the explicit ``isinstance(v, bool)`` check.
    pytest.param(
        "use_encryption", 1, "input.kmbox_net.use_encryption",
        id="use_encryption-int-1",
    ),
    pytest.param(
        "use_encryption", "true", "input.kmbox_net.use_encryption",
        id="use_encryption-string-true",
    ),
    pytest.param(
        "use_encryption", None, "input.kmbox_net.use_encryption",
        id="use_encryption-none",
    ),
]


@pytest.mark.unit
class TestLoadConfigRejectsMalformedKmboxKeys:
    """``load_config`` raises ``ConfigException`` naming the offending dotted
    key when ``input.kmbox_net.*`` contains a malformed value (Req 3.7-3.10)."""

    @pytest.mark.parametrize(
        "key,bad_value,dotted_key",
        _MALFORMED_KMBOX_CASES,
    )
    def test_malformed_kmbox_value_raises_with_dotted_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        key: str,
        bad_value: Any,
        dotted_key: str,
    ) -> None:
        """Each malformed leaf produces a ``ConfigException`` whose message
        contains the dotted key path of the offending key."""
        cfg = _config_with_kmbox_value(key, bad_value)
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, cfg)

        _point_loader_at(monkeypatch, config_path)

        with pytest.raises(
            ConfigException, match=re.escape(dotted_key)
        ):
            config.load_config()

    @pytest.mark.parametrize(
        "missing_key,dotted_key",
        [
            ("ip", "input.kmbox_net.ip"),
            ("port", "input.kmbox_net.port"),
            ("uuid", "input.kmbox_net.uuid"),
            ("use_encryption", "input.kmbox_net.use_encryption"),
        ],
    )
    def test_missing_kmbox_key_raises_with_dotted_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        missing_key: str,
        dotted_key: str,
    ) -> None:
        """A missing ``input.kmbox_net.<key>`` is a hard error per Req 3.7-3.10:
        ``load_config`` raises ``ConfigException`` naming the missing key
        (the loader does NOT silently default-fill ``input.kmbox_net.*``)."""
        cfg = _config_without_kmbox_value(missing_key)
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, cfg)

        _point_loader_at(monkeypatch, config_path)

        with pytest.raises(
            ConfigException, match=re.escape(dotted_key)
        ):
            config.load_config()
