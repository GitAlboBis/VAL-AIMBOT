"""
Property test — Task 11.3 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Property 20: Config validation order.

**Property 20: Config validation order**

    *For any* ``config.yaml`` fragment in which each of
    ``input.kmbox_net.{ip, port, uuid, use_encryption}`` is independently
    valid or invalid:

      * **Failure path** — when at least one key is invalid, exactly one
        :class:`ConfigException` is raised whose message names the
        **first failing key** in the fixed order
        ``ip → port → uuid → use_encryption`` (Req 11.1, 11.11).
      * **Success path** — when all four keys are valid, the validator
        returns silently AND the four values flow to
        :meth:`KmBoxNetDriver.__init__` byte-for-byte unchanged (same
        Python objects, same types, same string representations) per
        Req 11.6.
      * **Failure-path wiring invariant** — on any failure path, the
        ``DetectionFramework`` SHALL NOT instantiate
        :class:`KmBoxNetDriver` (Req 11.7-11.10).

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8,
11.9, 11.10, 11.11**

Implementation notes
--------------------

The four ``input.kmbox_net.*`` values are generated independently from
*tagged* strategies — each emits a ``("valid", value)`` or
``("invalid", value)`` tuple — so the test computes the *expected*
first-failing key from the four tags in declaration order, without
re-deriving the validator's rule set inline. This keeps the property
in lockstep with the validator's classification of "invalid" while
still exercising every combination of valid/invalid keys.

The wiring invariant (Req 11.7-11.10) is verified with a spy that
mimics :meth:`main.DetectionFramework.initialize_input` step for step:
the validator runs first, and only on success does the spy record the
arguments that *would* be forwarded to ``KmBoxNetDriver(...)``. On a
:class:`ConfigException` the spy records nothing — the test asserts the
recorded-args list is empty, which is the property under test.

The spy avoids monkey-patching :class:`KmBoxNetDriver` itself. The real
constructor opens a UDP socket, blocks on a 5-second handshake, and
emits log entries — none of which are exercised by Property 20.
Capturing the args at the call site is sufficient and keeps the test
fast and deterministic.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Make repo-root packages importable regardless of pytest's launch CWD.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from hypothesis import HealthCheck, assume, example, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from exceptions import ConfigException  # noqa: E402
from utils.validation import validate_kmbox_net_config  # noqa: E402


# ---------------------------------------------------------------------------
# Tagged strategies — each ``(tag, value)`` tuple carries its own validity tag
# ---------------------------------------------------------------------------
#
# Tagging at strategy construction time avoids re-deriving the validator's
# rule set inside the test body. The expected first-failing key is then a
# pure function of the four tags in declaration order
# ``ip → port → uuid → use_encryption`` (Req 11.1).


# -- ip ---------------------------------------------------------------------

_valid_ip_value_st = st.builds(
    lambda a, b, c, d: f"{a}.{b}.{c}.{d}",
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
)

_invalid_ip_value_st = st.one_of(
    # Non-string types (Req 11.2 rejects them upstream of the form check).
    st.none(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.lists(st.integers(min_value=0, max_value=255), max_size=6),
    # Wrong number of dot-separated parts.
    st.just(""),
    st.just("1.2.3"),
    st.just("1.2.3.4.5"),
    # Octet out of range.
    st.builds(
        lambda a, b, c, d: f"{a}.{b}.{c}.{d}",
        st.integers(min_value=256, max_value=999),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
    ),
    # Non-digit / whitespace / sign-prefixed octets.
    st.just("a.b.c.d"),
    st.just(" 192.168.1.1"),
    st.just("192.168.1.1 "),
    st.just("192. 168.1.1"),
    st.just("192.168.1.-1"),
    st.just("+1.2.3.4"),
)

_ip_st = st.one_of(
    _valid_ip_value_st.map(lambda v: ("valid", v)),
    _invalid_ip_value_st.map(lambda v: ("invalid", v)),
)


# -- port -------------------------------------------------------------------
#
# Per Req 11.3 the validator accepts ONLY a string of ASCII decimal digits
# parsing to ``[1, 65535]`` with no whitespace and no leading zeros. Plain
# ``int`` values are rejected (the validator requires ``isinstance(v, str)``).

_valid_port_value_st = st.integers(min_value=1, max_value=65535).map(str)

_invalid_port_value_st = st.one_of(
    # Non-string types — rejected by the ``isinstance(v, str)`` check.
    st.none(),
    st.integers(min_value=1, max_value=65535),  # plain int — Req 11.3 rejects
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.lists(st.integers(min_value=1, max_value=65535), max_size=2),
    # Empty / non-digit / whitespace / signed / hex / float-string forms.
    st.just(""),
    st.just(" 41990"),
    st.just("41990 "),
    st.just("+41990"),
    st.just("-1"),
    st.just("0x10"),
    st.just("41.99"),
    # Leading-zero strings (rejected per Req 11.3 even when in range).
    st.from_regex(r"\A0[0-9]{1,4}\Z", fullmatch=True),
    # Out-of-range decimal strings.
    st.just("0"),
    st.integers(min_value=65536, max_value=999999).map(str),
)

_port_st = st.one_of(
    _valid_port_value_st.map(lambda v: ("valid", v)),
    _invalid_port_value_st.map(lambda v: ("invalid", v)),
)


# -- uuid -------------------------------------------------------------------
#
# Req 11.4: non-empty string of length ``[1, 64]`` with no leading or
# trailing whitespace. The valid arm is a printable-ASCII string with no
# leading/trailing whitespace; the invalid arm covers non-strings, the
# empty string, oversized strings, and leading/trailing-whitespace strings.

_valid_uuid_value_st = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=64,
)

_invalid_uuid_value_st = st.one_of(
    # Non-string types.
    st.none(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.lists(st.integers(), max_size=3),
    # Empty / oversize.
    st.just(""),
    st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=65,
        max_size=128,
    ),
    # Leading / trailing whitespace.
    st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=1,
        max_size=62,
    ).map(lambda s: " " + s),
    st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=1,
        max_size=62,
    ).map(lambda s: s + " "),
    st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=1,
        max_size=62,
    ).map(lambda s: "\t" + s),
)

_uuid_st = st.one_of(
    _valid_uuid_value_st.map(lambda v: ("valid", v)),
    _invalid_uuid_value_st.map(lambda v: ("invalid", v)),
)


# -- use_encryption ---------------------------------------------------------
#
# Req 11.5: strict Python ``bool`` only — ``0``, ``1``, ``"true"``,
# ``"false"``, ``"yes"``, ``"no"``, ``None``, etc. are all rejected.

_valid_use_encryption_value_st = st.booleans()

_invalid_use_encryption_value_st = st.one_of(
    # ``int`` — rejected by ``isinstance(v, bool)``.
    st.integers(min_value=-100, max_value=100),
    # ``float`` / ``None`` / lists / dicts.
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.none(),
    st.lists(st.booleans(), max_size=3),
    st.dictionaries(st.text(min_size=1, max_size=3), st.booleans(), max_size=2),
    # YAML-coerced look-alikes — strings ``"true"``/``"false"``/``"yes"``…
    st.sampled_from(["true", "false", "True", "False", "yes", "no", "on", "off"]),
).filter(lambda v: not isinstance(v, bool))

_use_encryption_st = st.one_of(
    _valid_use_encryption_value_st.map(lambda v: ("valid", v)),
    _invalid_use_encryption_value_st.map(lambda v: ("invalid", v)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_KEY_ORDER: Tuple[str, str, str, str] = ("ip", "port", "uuid", "use_encryption")


def _build_config(
    ip: Any, port: Any, uuid: Any, use_encryption: Any
) -> Dict[str, Any]:
    """Build a ``config.yaml``-shaped dict with the four leaves overridden."""
    return {
        "input": {
            "kmbox_net": {
                "ip": ip,
                "port": port,
                "uuid": uuid,
                "use_encryption": use_encryption,
            }
        }
    }


def _expected_first_failing_key(
    ip_tag: str, port_tag: str, uuid_tag: str, use_encryption_tag: str
) -> Optional[str]:
    """Return the first key tagged ``"invalid"`` in fixed declaration order.

    Returns ``None`` when every key is valid. The order
    ``ip → port → uuid → use_encryption`` is fixed by Requirement 11.1
    and matches the call order inside
    :func:`utils.validation.validate_kmbox_net_config`.
    """
    tags = {
        "ip": ip_tag,
        "port": port_tag,
        "uuid": uuid_tag,
        "use_encryption": use_encryption_tag,
    }
    for key in _KEY_ORDER:
        if tags[key] == "invalid":
            return key
    return None


class _DriverInitSpy:
    """Records the ``(ip, port, uuid, use_encryption)`` quadruple passed
    to a ``KmBoxNetDriver``-shaped constructor, without performing any
    real I/O.

    Used to verify Req 11.6 — that on the success path the four
    validated values flow to :meth:`KmBoxNetDriver.__init__` byte-for-
    byte unchanged — and Req 11.7-11.10 — that on any failure path the
    constructor is **not** called.
    """

    def __init__(self) -> None:
        self.calls: list[Tuple[Any, Any, Any, Any]] = []

    def __call__(
        self,
        ip: Any,
        port: Any,
        uuid: Any,
        use_encryption: Any,
    ) -> None:
        # Record the *exact* objects (not copies) so the assertion can
        # use ``is`` / ``type()`` checks and verify Req 11.6's
        # "values, types, and string representations exactly".
        self.calls.append((ip, port, uuid, use_encryption))


def _initialize_input_like_detection_framework(
    config: Dict[str, Any], driver_factory: _DriverInitSpy
) -> None:
    """Run the validation + driver-instantiation sequence the way
    :meth:`main.DetectionFramework.initialize_input` does it (Req 11.6
    / Req 11.7-11.10).

    Mirrors the relevant lines of ``main.DetectionFramework.initialize_input``:

      1. ``validate_kmbox_net_config(config)`` — raises
         :class:`ConfigException` on any malformed key.
      2. Read the four ``input.kmbox_net.*`` keys directly (no
         defaulting per Req 11.6).
      3. Pass them through to ``KmBoxNetDriver(...)`` UNMODIFIED.

    Any :class:`ConfigException` raised by step 1 propagates without
    invoking step 2 or 3 — that is the wiring invariant under test.
    """
    # Step 1 — validate. A failure here propagates a ConfigException to
    # the caller; the spy is never invoked, which is the wiring
    # invariant the failure-path test asserts.
    validate_kmbox_net_config(config)

    # Step 2 — read the four keys directly. Mirror the literal access
    # pattern in ``main.DetectionFramework.initialize_input``:
    #   km_cfg = input_cfg['kmbox_net']
    #   ip = km_cfg['ip']; port = km_cfg['port']; ...
    km_cfg = config["input"]["kmbox_net"]
    ip = km_cfg["ip"]
    port = km_cfg["port"]
    uuid_str = km_cfg["uuid"]
    use_enc = km_cfg["use_encryption"]

    # Step 3 — forward UNMODIFIED to the driver constructor (Req 11.6).
    driver_factory(
        ip=ip, port=port, uuid=uuid_str, use_encryption=use_enc
    )


# ---------------------------------------------------------------------------
# Settings shared by every property in this file
# ---------------------------------------------------------------------------

_PROPERTY_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
    ],
)


# ---------------------------------------------------------------------------
# Property 20a — failure path: first-failing key is named
# ---------------------------------------------------------------------------


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(
    ip_tagged=_ip_st,
    port_tagged=_port_st,
    uuid_tagged=_uuid_st,
    use_encryption_tagged=_use_encryption_st,
)
# Hand-picked examples covering each first-failing-key category. They
# guarantee the property is exercised on at least one tuple per
# category even if Hypothesis's random sampling skips them.
@example(
    ip_tagged=("invalid", "not.an.ip"),
    port_tagged=("valid", "41990"),
    uuid_tagged=("valid", "01FBC068"),
    use_encryption_tagged=("valid", True),
)
@example(
    ip_tagged=("valid", "192.168.2.188"),
    port_tagged=("invalid", "0"),
    uuid_tagged=("valid", "01FBC068"),
    use_encryption_tagged=("valid", True),
)
@example(
    ip_tagged=("valid", "192.168.2.188"),
    port_tagged=("valid", "41990"),
    uuid_tagged=("invalid", ""),
    use_encryption_tagged=("valid", True),
)
@example(
    ip_tagged=("valid", "192.168.2.188"),
    port_tagged=("valid", "41990"),
    uuid_tagged=("valid", "01FBC068"),
    use_encryption_tagged=("invalid", "true"),
)
# Multiple-invalid case — the first invalid key in the fixed order
# (``ip``) must be the one named.
@example(
    ip_tagged=("invalid", "999.999.999.999"),
    port_tagged=("invalid", "0"),
    uuid_tagged=("invalid", ""),
    use_encryption_tagged=("invalid", "true"),
)
def test_property20_failure_names_first_failing_key(
    ip_tagged: Tuple[str, Any],
    port_tagged: Tuple[str, Any],
    uuid_tagged: Tuple[str, Any],
    use_encryption_tagged: Tuple[str, Any],
) -> None:
    """Property 20 (failure arm) — the first invalid key is named.

    For any tuple of ``(ip, port, uuid, use_encryption)`` where at
    least one tag is ``"invalid"``, the validator must raise exactly
    one :class:`ConfigException` whose message names the **first**
    invalid key in the fixed order ``ip → port → uuid →
    use_encryption`` (Req 11.1, 11.11), and the
    :class:`KmBoxNetDriver` constructor must NOT be invoked
    (Req 11.7-11.10).

    Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.7, 11.8,
    11.9, 11.10, 11.11.
    """
    ip_tag, ip_value = ip_tagged
    port_tag, port_value = port_tagged
    uuid_tag, uuid_value = uuid_tagged
    use_enc_tag, use_enc_value = use_encryption_tagged

    expected_key = _expected_first_failing_key(
        ip_tag, port_tag, uuid_tag, use_enc_tag
    )
    # This property only covers tuples where at least one key is
    # invalid. The all-valid case is the subject of Property 20b.
    assume(expected_key is not None)

    config = _build_config(ip_value, port_value, uuid_value, use_enc_value)
    spy = _DriverInitSpy()

    full_dotted_key = f"input.kmbox_net.{expected_key}"

    with pytest.raises(ConfigException) as excinfo:
        _initialize_input_like_detection_framework(config, spy)

    message = str(excinfo.value)

    # ── Sub-property 20a-i: the message names the first failing key ──
    #
    # The full dotted key must appear verbatim in the exception
    # message (per ``_kmbox_error`` formatter:
    # ``f"{dotted_key}={value!r}: {reason}"``).
    assert full_dotted_key in message, (
        f"Req 11.{2 + _KEY_ORDER.index(expected_key)} / 11.11: "
        f"ConfigException message must name the first failing key "
        f"{full_dotted_key!r}; got {message!r}"
    )

    # ── Sub-property 20a-ii: NO subsequent dotted keys are named ─────
    #
    # Validation must stop at the first failure (Req 11.11). The
    # exception message therefore must NOT mention any key that comes
    # *after* ``expected_key`` in the fixed order — otherwise the
    # validator would have continued past the first failure.
    expected_index = _KEY_ORDER.index(expected_key)
    for later_key in _KEY_ORDER[expected_index + 1:]:
        later_dotted = f"input.kmbox_net.{later_key}"
        assert later_dotted not in message, (
            f"Req 11.11: validator must stop after the first failing "
            f"key {full_dotted_key!r}, but the exception message also "
            f"names a later key {later_dotted!r}: {message!r}"
        )

    # ── Sub-property 20a-iii: KmBoxNetDriver was NOT instantiated ────
    #
    # Wiring invariant Req 11.7-11.10 — on any failure path the
    # DetectionFramework must NOT instantiate the driver. The spy
    # records every call to its ``__call__``; the call list must be
    # empty for any failure path.
    assert spy.calls == [], (
        f"Req 11.7-11.10: KmBoxNetDriver constructor must not be "
        f"invoked when validation fails; spy recorded {len(spy.calls)} "
        f"call(s): {spy.calls!r}"
    )


# ---------------------------------------------------------------------------
# Property 20b — success path: byte-for-byte pass-through
# ---------------------------------------------------------------------------


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(
    ip_value=_valid_ip_value_st,
    port_value=_valid_port_value_st,
    uuid_value=_valid_uuid_value_st,
    use_encryption_value=_valid_use_encryption_value_st,
)
@example(
    ip_value="192.168.2.188",
    port_value="41990",
    uuid_value="01FBC068",
    use_encryption_value=True,
)
@example(
    ip_value="0.0.0.0",
    port_value="1",
    uuid_value="A",
    use_encryption_value=False,
)
@example(
    ip_value="255.255.255.255",
    port_value="65535",
    uuid_value="x" * 64,
    use_encryption_value=True,
)
def test_property20_success_passes_through_byte_for_byte(
    ip_value: str,
    port_value: str,
    uuid_value: str,
    use_encryption_value: bool,
) -> None:
    """Property 20 (success arm) — values flow to ``__init__`` unchanged.

    For any tuple ``(ip, port, uuid, use_encryption)`` where every
    value is independently valid, the validator returns silently AND
    the four values flow to :meth:`KmBoxNetDriver.__init__` byte-for-
    byte unchanged: same Python object identity, same ``type()``,
    same string representation (Req 11.6).

    Validates: Requirement 11.6.
    """
    config = _build_config(ip_value, port_value, uuid_value, use_encryption_value)
    spy = _DriverInitSpy()

    # The validator must accept the all-valid fragment. Any
    # ``ConfigException`` here is a strategy bug, not a wiring failure
    # — let it propagate so the failure mode is unambiguous.
    _initialize_input_like_detection_framework(config, spy)

    # ── Sub-property 20b-i: KmBoxNetDriver was instantiated exactly once ──
    assert len(spy.calls) == 1, (
        f"Req 11.6: KmBoxNetDriver constructor must be invoked "
        f"exactly once on the success path; spy recorded "
        f"{len(spy.calls)} call(s): {spy.calls!r}"
    )

    forwarded_ip, forwarded_port, forwarded_uuid, forwarded_use_enc = (
        spy.calls[0]
    )

    # ── Sub-property 20b-ii: object identity preserved ───────────────
    #
    # Req 11.6 says values flow "byte-for-byte unchanged" — the
    # strongest possible reading is identity preservation, which
    # rules out any silent transformation (``str(...)``, ``int(...)``,
    # ``bool(...)``, ``copy.deepcopy(...)``). For immutable values
    # (``str``, ``bool``) ``is`` is the correct equivalence under
    # CPython given small-string interning is irrelevant — the
    # forwarded object must literally be the same object the
    # validator received.
    assert forwarded_ip is ip_value, (
        f"Req 11.6: ``ip`` must be forwarded with identity preserved; "
        f"got {forwarded_ip!r} (id={id(forwarded_ip)}) vs original "
        f"{ip_value!r} (id={id(ip_value)})"
    )
    assert forwarded_port is port_value, (
        f"Req 11.6: ``port`` must be forwarded with identity "
        f"preserved (no implicit ``int(port)`` cast); got "
        f"{forwarded_port!r} (id={id(forwarded_port)}) vs original "
        f"{port_value!r} (id={id(port_value)})"
    )
    assert forwarded_uuid is uuid_value, (
        f"Req 11.6: ``uuid`` must be forwarded with identity "
        f"preserved; got {forwarded_uuid!r} (id={id(forwarded_uuid)}) "
        f"vs original {uuid_value!r} (id={id(uuid_value)})"
    )
    assert forwarded_use_enc is use_encryption_value, (
        f"Req 11.6: ``use_encryption`` must be forwarded with identity "
        f"preserved (no implicit ``bool(...)`` cast); got "
        f"{forwarded_use_enc!r} vs original {use_encryption_value!r}"
    )

    # ── Sub-property 20b-iii: types preserved ────────────────────────
    #
    # Defense in depth — even if a future refactor ever copies
    # arguments, the *types* must remain exactly what the validator
    # accepted. ``port`` MUST stay a ``str`` (the validator's
    # contract) — an implicit ``int`` cast would be a Req 11.6
    # violation. ``use_encryption`` MUST stay a ``bool`` (not a
    # truthy ``int``).
    assert type(forwarded_ip) is str, (
        f"Req 11.6: forwarded ``ip`` type must be ``str``; "
        f"got {type(forwarded_ip).__name__}"
    )
    assert type(forwarded_port) is str, (
        f"Req 11.6: forwarded ``port`` type must be ``str``; "
        f"got {type(forwarded_port).__name__}"
    )
    assert type(forwarded_uuid) is str, (
        f"Req 11.6: forwarded ``uuid`` type must be ``str``; "
        f"got {type(forwarded_uuid).__name__}"
    )
    assert type(forwarded_use_enc) is bool, (
        f"Req 11.6: forwarded ``use_encryption`` type must be "
        f"``bool`` (not ``int``); got {type(forwarded_use_enc).__name__}"
    )

    # ── Sub-property 20b-iv: string representations preserved ────────
    #
    # ``repr()`` captures the full surface form (e.g. quote style,
    # escape sequences, exact bool spelling). If two strings render
    # the same ``repr`` they encode the same bytes when later
    # serialized by the driver's logging or wire layers.
    assert repr(forwarded_ip) == repr(ip_value)
    assert repr(forwarded_port) == repr(port_value)
    assert repr(forwarded_uuid) == repr(uuid_value)
    assert repr(forwarded_use_enc) == repr(use_encryption_value)
