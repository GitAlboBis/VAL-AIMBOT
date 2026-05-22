"""
Example tests for ``config.load_config`` I/O failure modes
(KmBox Net Integration spec, task 1.4).

These tests exercise the loader's ``config.yaml`` I/O surface against the
contract in Req 3.11:

    "IF config.yaml is absent, unreadable, or not parseable as YAML, THEN
    the Config_Loader SHALL raise ``ConfigException`` indicating the
    configuration file failure."

and the "happy path" complement in Req 3.1:

    "THE Config_Loader SHALL read the keys ``input.kmbox_net.ip``,
    ``input.kmbox_net.port``, ``input.kmbox_net.uuid``, and
    ``input.kmbox_net.use_encryption`` from ``config.yaml``."

Each test points :data:`config._CONFIG_FILE` at a per-test artefact under
``tmp_path`` via :class:`pytest.MonkeyPatch`, so the suite is fully
hermetic and never reads or writes the workspace's live ``config.yaml``.

Validates: Requirements 3.1, 3.11
"""

from __future__ import annotations

import builtins
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


# ---------------------------------------------------------------------------
# Req 3.11 — absent / unreadable / unparseable config.yaml
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConfigYamlAbsent:
    """Loader rejects a missing ``config.yaml`` with ``ConfigException``."""

    def test_missing_file_raises_config_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A path that does not exist produces ``ConfigException``."""
        missing = tmp_path / "does_not_exist" / "config.yaml"
        assert not missing.exists()

        _point_loader_at(monkeypatch, missing)

        with pytest.raises(ConfigException) as exc_info:
            config.load_config()

        message = str(exc_info.value)
        # The loader's "not found" branch names the path so operators can
        # locate the missing file.
        assert "config.yaml" in message or str(missing) in message, (
            f"Missing-file ConfigException should reference the config "
            f"path; got: {message!r}"
        )

    def test_missing_file_does_not_create_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading a missing config must not write a file to disk (Req 2.6 / 3.11)."""
        missing = tmp_path / "config.yaml"
        assert not missing.exists()

        _point_loader_at(monkeypatch, missing)

        with pytest.raises(ConfigException):
            config.load_config()

        assert not missing.exists(), (
            "load_config() must not create config.yaml when it is absent"
        )


@pytest.mark.unit
class TestConfigYamlUnreadable:
    """Loader rejects an unreadable ``config.yaml`` with ``ConfigException``."""

    def test_open_oserror_raises_config_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An ``OSError`` from ``open()`` is wrapped as ``ConfigException``.

        Simulates a permission-denied / locked-file scenario by patching
        :func:`builtins.open` so it raises ``OSError`` for the configured
        path. This is platform-independent and avoids relying on
        Windows/POSIX permission semantics.
        """
        config_path = tmp_path / "config.yaml"
        config_path.write_text("dummy: 1", encoding="utf-8")

        _point_loader_at(monkeypatch, config_path)

        real_open = builtins.open
        target = str(config_path)

        def fake_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(file) == target:
                raise OSError("simulated read failure")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fake_open)

        with pytest.raises(ConfigException) as exc_info:
            config.load_config()

        message = str(exc_info.value)
        # The loader's read-error branch surfaces the underlying I/O cause.
        assert "config.yaml" in message or "read" in message.lower(), (
            f"Unreadable-file ConfigException should mention the file or "
            f"the read failure; got: {message!r}"
        )

    def test_path_is_a_directory_raises_config_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A path that exists but cannot be opened as a file is rejected.

        Pointing the loader at a directory triggers ``IsADirectoryError`` on
        POSIX and ``PermissionError`` on Windows. Both inherit from
        ``OSError``, which the loader catches and wraps as ``ConfigException``.
        """
        directory = tmp_path / "config_dir"
        directory.mkdir()
        assert directory.exists() and directory.is_dir()

        _point_loader_at(monkeypatch, directory)

        with pytest.raises(ConfigException):
            config.load_config()


@pytest.mark.unit
class TestConfigYamlUnparseable:
    """Loader rejects an unparseable ``config.yaml`` with ``ConfigException``."""

    @pytest.mark.parametrize(
        "bad_yaml,case_id",
        [
            ("foo: [unclosed\n", "unclosed-flow-sequence"),
            ("key: value\n  bad_indent: 1\n :::\n", "stray-colons"),
            ("a: 1\n\tb: 2\n", "tab-indent"),
            ("foo: \"unterminated string\n", "unterminated-string"),
            ("{unbalanced: [a, b, c}\n", "unbalanced-braces"),
            ("- item1\nkey: value\n", "mixed-sequence-mapping"),
            ("@invalid_token: 1\n", "yaml-reserved-character"),
        ],
        ids=lambda v: v if isinstance(v, str) and len(v) <= 32 else None,
    )
    def test_invalid_yaml_raises_config_exception(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        bad_yaml: str,
        case_id: str,
    ) -> None:
        """Each malformed YAML payload produces ``ConfigException``."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(bad_yaml, encoding="utf-8")

        # Sanity-check the test fixture: the payload must actually be
        # unparseable; if PyYAML accepts it the test is meaningless.
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(bad_yaml)

        _point_loader_at(monkeypatch, config_path)

        with pytest.raises(ConfigException) as exc_info:
            config.load_config()

        message = str(exc_info.value)
        assert "parse" in message.lower() or "config.yaml" in message, (
            f"Parse-error ConfigException should mention the file or the "
            f"parse failure; case={case_id!r}, message={message!r}"
        )

    def test_invalid_yaml_does_not_modify_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The loader never writes back to a malformed config (Req 2.6)."""
        config_path = tmp_path / "config.yaml"
        bad_yaml = "foo: [unclosed\n"
        config_path.write_text(bad_yaml, encoding="utf-8")
        original_bytes = config_path.read_bytes()

        _point_loader_at(monkeypatch, config_path)

        with pytest.raises(ConfigException):
            config.load_config()

        assert config_path.read_bytes() == original_bytes, (
            "load_config() must not rewrite config.yaml on parse failure"
        )


# ---------------------------------------------------------------------------
# Req 3.1 — minimal-valid-config loads and exposes the four kmbox_net keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMinimalValidConfigLoads:
    """A minimal valid config loads and exposes ``input.kmbox_net.*``."""

    def test_minimal_valid_config_returns_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``load_config`` returns a dict on a valid minimal config."""
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, _minimal_valid_config())

        _point_loader_at(monkeypatch, config_path)

        loaded = config.load_config()
        assert isinstance(loaded, dict)

    def test_minimal_valid_config_exposes_kmbox_net_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All four ``input.kmbox_net.*`` keys survive ``load_config`` (Req 3.1)."""
        expected = _minimal_valid_config()
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, expected)

        _point_loader_at(monkeypatch, config_path)

        loaded = config.load_config()

        kmbox_section = loaded.get("input", {}).get("kmbox_net")
        assert isinstance(kmbox_section, dict), (
            f"Expected input.kmbox_net to be a mapping, got "
            f"{type(kmbox_section).__name__}"
        )

        # Req 3.1 — the four keys MUST be readable from the loaded dict.
        for key in ("ip", "port", "uuid", "use_encryption"):
            assert key in kmbox_section, (
                f"input.kmbox_net.{key} missing from loaded config"
            )

        # And the values must round-trip byte-equal to the source file.
        expected_kmbox = expected["input"]["kmbox_net"]
        assert kmbox_section["ip"] == expected_kmbox["ip"]
        assert kmbox_section["port"] == expected_kmbox["port"]
        assert kmbox_section["uuid"] == expected_kmbox["uuid"]
        assert kmbox_section["use_encryption"] is expected_kmbox["use_encryption"]

    def test_minimal_valid_config_value_types(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loaded ``input.kmbox_net.*`` values have the types Req 3.2-3.5 require."""
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, _minimal_valid_config())

        _point_loader_at(monkeypatch, config_path)

        loaded = config.load_config()
        kmbox_section = loaded["input"]["kmbox_net"]

        assert isinstance(kmbox_section["ip"], str)
        assert isinstance(kmbox_section["port"], str)
        assert isinstance(kmbox_section["uuid"], str)
        # NB: ``bool`` is a subclass of ``int``; assert the strict bool type
        # to mirror the validator's ``isinstance(v, bool)`` check.
        assert isinstance(kmbox_section["use_encryption"], bool)

    def test_minimal_valid_config_does_not_modify_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``load_config`` must not write back to a successfully-loaded config (Req 2.6)."""
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, _minimal_valid_config())
        original_bytes = config_path.read_bytes()

        _point_loader_at(monkeypatch, config_path)

        config.load_config()

        assert config_path.read_bytes() == original_bytes, (
            "load_config() must not modify config.yaml on a successful load"
        )
