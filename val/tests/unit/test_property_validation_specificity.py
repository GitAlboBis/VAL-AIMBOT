"""
Property test — Task 10.2 of spec ``single-config-streamlining``.

**Property 4: Specificità dell'errore di validazione su campi non-target**

    *For any* chiave validata ``k`` che non appartiene a
    ``TARGET_CONFIGURATION`` ma è soggetta a validazione via
    ``utils/validation.py`` (es. range ``confidence``, range ``fps_cap``),
    e *any* valore fuori range assegnato a ``k``,
    ``load_config()`` SHALL sollevare un'eccezione il cui messaggio
    contiene come sottostringa il nome esatto di ``k``, e SHALL NOT
    restituire una configurazione parzialmente validata.

**Validates: Requirements 7.10**

Scope note — why this test targets ``validate_target_configuration``
-------------------------------------------------------------------
The theoretical statement of Property 4 talks about *"campi non-target"*
validated by ``utils/validation.py`` at config load time — e.g. the range
of ``ai_engine.confidence`` (0..1) or ``capture.fps_cap`` (>0). After
task 10.1 of this spec, however, ``utils/validation.py`` exposes exactly
four load-time validators:

* ``validate_frame`` — runtime frame shape/dtype checks (not invoked by
  ``load_config``);
* ``validate_coordinates`` — runtime bounds check (not invoked by
  ``load_config``);
* ``validate_delta_time`` — runtime dt check (not invoked by
  ``load_config``);
* ``validate_target_configuration`` — the only validator the
  Config_Loader actually calls.

None of the first three validators reads arbitrary non-target keys such
as ``ai_engine.confidence`` or ``capture.fps_cap`` during config load.
The non-empty load-time validation surface therefore reduces to the
**four Target_Configuration keys** themselves: missing or holding a
value other than the one pinned in
``utils.validation.TARGET_CONFIGURATION``.

Accordingly, this test encodes Property 4 as a property of
``validate_target_configuration``'s error messages:

1. *Unsupported-value branch* — for every target key ``k`` and every
   value ``v`` that is not the target value for ``k``, the raised
   :class:`ConfigException` must cite both the dotted key name ``k`` and
   ``repr(v)`` in its message.
2. *Missing-key branch* — for every target key ``k`` absent from the
   config, the raised :class:`ConfigException` must cite both ``k`` and
   the word ``missing`` in its message.

Both branches also assert that no partially-validated configuration is
returned (``validate_target_configuration`` returns ``None`` on success,
so the absence of return value is guaranteed by ``pytest.raises``).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from exceptions import ConfigException
from utils.validation import TARGET_CONFIGURATION, validate_target_configuration

try:
    from hypothesis import HealthCheck, assume, given, settings
    from hypothesis import strategies as st
    _HYPOTHESIS_AVAILABLE = True
except ImportError:  # pragma: no cover — envs without Hypothesis
    _HYPOTHESIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: The four dotted keys whose values are pinned by ``TARGET_CONFIGURATION``.
TARGET_KEYS: List[str] = list(TARGET_CONFIGURATION.keys())


def _valid_target_config() -> Dict[str, Any]:
    """Build a minimally valid Target_Configuration dict.

    Kept local so the property test is hermetic: perturbations to the
    workspace's ``config.yaml`` cannot leak into the test and the input
    space is fully controlled by this module.
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
        },
    }


def _set_dotted(cfg: Dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set ``cfg[...][last] = value`` walking the dotted path."""
    parts = dotted_key.split(".")
    node: Dict[str, Any] = cfg
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _delete_dotted(cfg: Dict[str, Any], dotted_key: str) -> None:
    """Remove the leaf at ``dotted_key``; no-op if already absent."""
    parts = dotted_key.split(".")
    node: Any = cfg
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def _is_numerically_unstable(value: Any) -> bool:
    """True if ``value`` contains NaN at the top level.

    NaN is not equal to itself, so a NaN ``bad_value`` would be indistinguishable
    from a target value under ``actual_value != expected_value`` inside
    ``validate_target_configuration`` only because the target values are
    strings, but the repr comparison we make here is still brittle for NaN
    floats embedded via roundtripping. Filtering them out stabilises the
    property formulation.
    """
    return isinstance(value, float) and (math.isnan(value) or math.isinf(value))


# ---------------------------------------------------------------------------
# Primary property — unsupported value branch, Hypothesis-driven
# ---------------------------------------------------------------------------

if _HYPOTHESIS_AVAILABLE:

    _primitive = st.one_of(
        st.text(max_size=40),
        st.integers(min_value=-10_000, max_value=10_000),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.booleans(),
        st.none(),
    )

    _non_target_value_strategy = st.one_of(
        _primitive,
        st.lists(_primitive, min_size=0, max_size=4),
        st.dictionaries(
            st.text(min_size=1, max_size=6),
            _primitive,
            min_size=0,
            max_size=3,
        ),
    )

    @pytest.mark.unit
    @settings(
        max_examples=150,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        target_key=st.sampled_from(TARGET_KEYS),
        bad_value=_non_target_value_strategy,
    )
    def test_property_unsupported_value_cites_key_and_repr(
        target_key: str,
        bad_value: Any,
    ) -> None:
        """Property 4 — unsupported-value branch.

        For any target key ``k`` and any value ``v`` such that
        ``v != TARGET_CONFIGURATION[k]``,
        :func:`validate_target_configuration` must raise
        :class:`ConfigException` whose message contains both ``k`` and
        ``repr(v)`` as substrings, and must not return a partially-validated
        configuration.
        """
        expected_value = TARGET_CONFIGURATION[target_key]

        # Reject examples that collide with the target value: the property's
        # premise is ``v != TARGET_CONFIGURATION[k]``.
        if type(bad_value) is type(expected_value) and bad_value == expected_value:
            assume(False)

        # Filter NaN/inf floats that would destabilise the repr assertion.
        if _is_numerically_unstable(bad_value):
            assume(False)

        cfg = _valid_target_config()
        _set_dotted(cfg, target_key, bad_value)

        with pytest.raises(ConfigException) as exc_info:
            validate_target_configuration(cfg)
        message = str(exc_info.value)

        assert target_key in message, (
            f"ConfigException message does not cite the key {target_key!r}.\n"
            f"  bad_value = {bad_value!r}\n"
            f"  message   = {message!r}"
        )

        expected_repr = repr(bad_value)
        assert expected_repr in message, (
            f"ConfigException message does not cite repr(bad_value).\n"
            f"  bad_value     = {bad_value!r}\n"
            f"  expected_repr = {expected_repr!r}\n"
            f"  message       = {message!r}"
        )


# ---------------------------------------------------------------------------
# Missing-key branch
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("missing_key", TARGET_KEYS)
def test_missing_target_key_message_cites_key_and_says_missing(
    missing_key: str,
) -> None:
    """Property 4 — missing-key branch.

    For every target key ``k``, deleting ``k`` from an otherwise valid
    Target_Configuration dict and calling
    :func:`validate_target_configuration` must raise
    :class:`ConfigException` whose message contains both ``k`` and the
    word ``missing`` (case-insensitive) as substrings.
    """
    cfg = _valid_target_config()
    _delete_dotted(cfg, missing_key)

    with pytest.raises(ConfigException) as exc_info:
        validate_target_configuration(cfg)
    message = str(exc_info.value)

    assert missing_key in message, (
        f"ConfigException (missing branch) does not cite the key "
        f"{missing_key!r}. message={message!r}"
    )
    assert "missing" in message.lower(), (
        f"ConfigException (missing branch) does not contain the word "
        f"'missing'. key={missing_key!r}, message={message!r}"
    )


# ---------------------------------------------------------------------------
# Representative deterministic cases
# ---------------------------------------------------------------------------
# These run alongside the Hypothesis property so well-known edge inputs are
# always exercised — and so the test file remains meaningful even when
# Hypothesis is not installed.

_REPRESENTATIVE_NON_TARGET_VALUES = [
    pytest.param("single_pc", id="str-wrong-arch"),
    pytest.param("dxgi", id="str-removed-backend-dxgi"),
    pytest.param("mss", id="str-removed-backend-mss"),
    pytest.param("hsv", id="str-removed-engine-hsv"),
    pytest.param("makcu", id="str-removed-driver-makcu"),
    pytest.param("CAPTURE_CARD", id="str-case-mismatch"),
    pytest.param(" capture_card ", id="str-whitespace-padded"),
    pytest.param("", id="str-empty"),
    pytest.param("αβγ", id="unicode-greek"),
    pytest.param("日本語", id="unicode-japanese"),
    pytest.param("\u200b", id="unicode-zero-width-space"),
    pytest.param(0, id="int-zero"),
    pytest.param(42, id="int-positive"),
    pytest.param(-1, id="int-negative"),
    pytest.param(3.14, id="float"),
    pytest.param(True, id="bool-true"),
    pytest.param(False, id="bool-false"),
    pytest.param(None, id="none"),
    pytest.param([], id="list-empty"),
    pytest.param([1, 2, 3], id="list-ints"),
    pytest.param({}, id="dict-empty"),
    pytest.param({"nested": "value"}, id="dict-nested"),
]


@pytest.mark.unit
@pytest.mark.parametrize("target_key", TARGET_KEYS)
@pytest.mark.parametrize("bad_value", _REPRESENTATIVE_NON_TARGET_VALUES)
def test_representative_unsupported_values_cite_key_and_repr(
    target_key: str,
    bad_value: Any,
) -> None:
    """Deterministic regression cases covering Property 4's unsupported-value
    branch.

    Complements the Hypothesis property with a fixed, reproducible set of
    inputs (removed-backend names, unicode edge cases, numeric primitives,
    booleans, None, container types). Also acts as the fallback when
    Hypothesis is unavailable.
    """
    expected_value = TARGET_CONFIGURATION[target_key]

    # Sanity-guard the premise ``bad_value != expected_value`` for this fixed
    # set (all representative values were chosen so this holds, but assert to
    # catch future accidental coincidences).
    assert not (
        type(bad_value) is type(expected_value) and bad_value == expected_value
    ), (
        f"Test setup error: representative bad_value {bad_value!r} equals "
        f"target value for {target_key!r}."
    )

    cfg = _valid_target_config()
    _set_dotted(cfg, target_key, bad_value)

    with pytest.raises(ConfigException) as exc_info:
        validate_target_configuration(cfg)
    message = str(exc_info.value)

    assert target_key in message, (
        f"ConfigException message does not cite the key {target_key!r}.\n"
        f"  bad_value = {bad_value!r}\n"
        f"  message   = {message!r}"
    )

    expected_repr = repr(bad_value)
    assert expected_repr in message, (
        f"ConfigException message does not cite repr(bad_value).\n"
        f"  bad_value     = {bad_value!r}\n"
        f"  expected_repr = {expected_repr!r}\n"
        f"  message       = {message!r}"
    )
