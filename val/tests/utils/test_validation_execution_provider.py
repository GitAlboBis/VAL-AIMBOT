"""
Unit tests for ``utils.validation.validate_execution_provider_value``.

Spec: ``.kiro/specs/npu-qnn-provider`` — Task 1.4.

These tests pin the schema described by Reqs 4.1 / 4.6 / 4.9 of the NPU QNN
provider spec:

- Allowed string values are normalized to lowercase and stripped of
  surrounding whitespace (Req 4.1).
- Unknown string values fall back to ``"auto"`` after emitting a WARN log
  naming the offending value (Req 4.6).
- Structural mismatches — ``list``, ``dict`` or any non-string scalar — are
  rejected with :class:`ConfigException` so a malformed config fails the
  load loudly rather than silently degrading the EP_Selector to ``auto``
  (Req 4.9).
"""

import logging

import pytest

from exceptions import ConfigException
from utils.validation import validate_execution_provider_value


# ---------------------------------------------------------------------------
# Req 4.1 — case-insensitive normalization across the allowed set
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_accepts_each_allowed_value_case_insensitive() -> None:
    """``"AUTO"``, ``" qnn "``, ``"DirectML"`` and ``"CPU"`` normalize to the
    canonical lowercase form (Req 4.1).

    Mixed casing and surrounding whitespace are common in hand-edited YAML
    files; the validator must accept them transparently so the cascade
    receives a stable, lowercased identifier downstream.
    """
    assert validate_execution_provider_value("AUTO") == "auto"
    assert validate_execution_provider_value(" qnn ") == "qnn"
    assert validate_execution_provider_value("DirectML") == "directml"
    assert validate_execution_provider_value("CPU") == "cpu"


# ---------------------------------------------------------------------------
# Req 4.9 — schema conflicts (list / dict / non-string scalar) are hard errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rejects_list_with_config_exception() -> None:
    """A YAML list at ``ai_engine.execution_provider`` is a schema conflict
    (Req 4.9). The validator must raise :class:`ConfigException` rather than
    coercing or silently falling back so the loader fails loudly with a
    message naming the dotted key and the offending value.
    """
    with pytest.raises(ConfigException) as exc_info:
        validate_execution_provider_value(["qnn"])

    message = str(exc_info.value)
    assert "ai_engine.execution_provider" in message
    assert "['qnn']" in message


@pytest.mark.unit
def test_rejects_dict_with_config_exception() -> None:
    """A YAML mapping at ``ai_engine.execution_provider`` is a schema
    conflict (Req 4.9). Same expectation as the list case: hard
    :class:`ConfigException` with the dotted key in the message.
    """
    with pytest.raises(ConfigException) as exc_info:
        validate_execution_provider_value({"ep": "qnn"})

    message = str(exc_info.value)
    assert "ai_engine.execution_provider" in message


@pytest.mark.unit
def test_rejects_non_string_scalar_with_config_exception() -> None:
    """A non-string scalar (``42``) is rejected with
    :class:`ConfigException` (Req 4.9). The error message names the type
    so the user can spot a YAML-quoting mistake (``42`` vs ``"42"``)
    without diffing source.
    """
    with pytest.raises(ConfigException) as exc_info:
        validate_execution_provider_value(42)

    message = str(exc_info.value)
    assert "ai_engine.execution_provider" in message
    assert "int" in message


# ---------------------------------------------------------------------------
# Req 4.6 — unknown string warns and falls back to "auto"
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_unknown_string_warns_and_falls_back_to_auto(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unrecognised string (``"hexagon"``) is not a schema conflict: the
    validator returns ``"auto"`` and emits a WARN identifying the offending
    value (Req 4.6).

    The fallback keeps the engine bootable in the face of a fat-finger
    while still surfacing the typo via the log record.
    """
    # Capture WARNING records emitted by ``utils.validation``. The validator
    # uses the module-level logger declared at the top of ``validation.py``.
    with caplog.at_level(logging.WARNING, logger="utils.validation"):
        result = validate_execution_provider_value("hexagon")

    assert result == "auto"

    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warn_records, (
        "Expected a WARN log record for the unrecognised execution-provider "
        "value, got none. Captured records: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )

    combined_message = " ".join(r.getMessage() for r in warn_records)
    assert "hexagon" in combined_message, (
        "WARN log must name the offending value 'hexagon' so the operator "
        f"can identify the typo. Got: {combined_message!r}"
    )
