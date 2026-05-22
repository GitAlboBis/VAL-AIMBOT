"""
Property test — Task 1.3 of spec ``kmbox-net-integration``.

# Feature: kmbox-net-integration, Property 6: Config validation rejects
#   malformed ``input.kmbox_net.*`` keys.

**Property 6: Config validation rejects malformed ``input.kmbox_net.*`` keys**

    *For any* malformed value of an ``input.kmbox_net`` key drawn from the
    following invalid-value generators —

    - ``ip``: not-a-string; string with ≠ 4 dot-separated parts; any part not
      decimal-only; any part outside ``0..255``;
    - ``port``: not-a-string; string containing non-digits; numeric value
      ``≤ 0`` or ``> 65535``;
    - ``uuid``: not-a-string; empty string; string longer than 64 characters;
    - ``use_encryption``: any value for which ``isinstance(v, bool)`` is
      ``False`` (including ``0``, ``1``, ``"true"``, ``None``)

    — :func:`utils.validation.validate_kmbox_net_config` SHALL raise
    :class:`ConfigException` whose message contains the dotted key path of
    the offending key (``"input.kmbox_net.ip"``, ``"input.kmbox_net.port"``,
    ``"input.kmbox_net.uuid"``, ``"input.kmbox_net.use_encryption"``).

**Validates: Requirements 3.7, 3.8, 3.9, 3.10**

Implementation notes
--------------------
The test file follows the convention "one ``@hypothesis.given`` per key"
described in the task plan, with curated invalid-value generators for each
of the four ``input.kmbox_net.*`` leaves. Each property assertion uses
``pytest.raises(ConfigException, match=<dotted-key>)`` so the dotted key
path must appear in the exception message text.

To ensure each per-key check exercises only that key's validator, every test
starts from a fully-valid ``input.kmbox_net`` block and mutates a single
leaf to a value drawn from the curated invalid-value strategy. The
validator checks keys in declaration order (``ip`` → ``port`` → ``uuid`` →
``use_encryption``) so a precondition shared with the other keys cannot
mask the property under test.
"""

from __future__ import annotations

import re
from typing import Any, Dict

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from exceptions import ConfigException
from utils.validation import validate_kmbox_net_config


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _valid_kmbox_config() -> Dict[str, Any]:
    """Return a fresh fully-valid ``input.kmbox_net.*`` config dict.

    The returned dict mirrors the real ``config.yaml`` layout: an ``input``
    mapping that contains a ``kmbox_net`` mapping with the four leaves.
    Values are picked from the live ``config.yaml`` so the baseline is
    representative of an actual running system.
    """
    return {
        "input": {
            "kmbox_net": {
                "ip": "192.168.2.188",
                "port": "6234",
                "uuid": "00000000-0000-0000-0000-000000000000",
                "use_encryption": True,
            }
        }
    }


def _with_kmbox_value(key: str, value: Any) -> Dict[str, Any]:
    """Build a config dict with ``input.kmbox_net.<key>`` overridden."""
    cfg = _valid_kmbox_config()
    cfg["input"]["kmbox_net"][key] = value
    return cfg


# Common Hypothesis settings for every property in this file.
# ``max_examples=100`` per the task plan ("@settings(max_examples=100)").
_PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategy: non-string values used as a sub-strategy for ip / port / uuid
# ---------------------------------------------------------------------------
#
# A non-string value covers the "not-a-string" branch shared by the ip / port
# / uuid validators. ``bool`` values are filtered out so the per-key strategies
# cleanly partition the input space (they are exercised by the dedicated
# ``use_encryption`` strategy below).
_non_string_strategy = st.one_of(
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.none(),
    st.lists(st.integers(min_value=-100, max_value=100), max_size=4),
    st.tuples(st.integers(), st.integers()),
    st.dictionaries(
        st.text(min_size=1, max_size=4), st.text(max_size=4), max_size=2
    ),
).filter(lambda v: not isinstance(v, str))


# ---------------------------------------------------------------------------
# IP strategies — invalid IPv4 dotted-quad values
# ---------------------------------------------------------------------------
#
# An ip is malformed when it is:
#   (a) not a string, or
#   (b) a string with ``.split('.')`` length other than 4, or
#   (c) a 4-part string where at least one part is not decimal-digit-only, or
#   (d) a 4-part decimal-digit-only string where at least one part > 255.


def _ip_wrong_part_count() -> st.SearchStrategy[str]:
    """Strings with ``.split('.')`` length not equal to 4."""
    return st.lists(
        st.from_regex(r"\A[0-9]{1,3}\Z", fullmatch=True),
        min_size=0,
        max_size=8,
    ).map(lambda parts: ".".join(parts)).filter(
        lambda s: len(s.split(".")) != 4
    )


def _ip_non_digit_octet() -> st.SearchStrategy[str]:
    """4-part strings where at least one part is not a decimal-digit string."""

    # Either an empty segment (e.g. ``"192..2.188"``), a sign-prefixed segment
    # (``"-1.0.0.0"``, ``"+1.0.0.0"``), or an alpha/punctuation-tainted
    # segment (``"abc.0.0.0"``, ``"1a.0.0.0"``, ``" 1.0.0.0"``).
    bad_part = st.one_of(
        st.just(""),
        st.from_regex(r"\A[+-][0-9]{1,3}\Z", fullmatch=True),
        st.from_regex(r"\A[a-zA-Z][0-9a-zA-Z]{0,3}\Z", fullmatch=True),
        st.from_regex(r"\A[0-9]{1,3}[a-zA-Z]\Z", fullmatch=True),
        st.text(
            alphabet=st.characters(blacklist_characters=".0123456789"),
            min_size=1,
            max_size=4,
        ),
    )
    good_part = st.from_regex(
        r"\A(0|1[0-9]{0,2}|2[0-4][0-9]|25[0-5])\Z", fullmatch=True
    )

    def _build(packed):
        position, octets, bad = packed
        result = list(octets)
        result[position] = bad
        return ".".join(result)

    return st.tuples(
        st.integers(min_value=0, max_value=3),
        st.tuples(good_part, good_part, good_part, good_part),
        bad_part,
    ).map(_build)


def _ip_octet_out_of_range() -> st.SearchStrategy[str]:
    """4-part decimal-digit strings with at least one octet ``> 255``."""
    good_octet = st.integers(min_value=0, max_value=255).map(str)
    bad_octet = st.integers(min_value=256, max_value=999).map(str)

    def _build(packed):
        position, octets, bad = packed
        result = list(octets)
        result[position] = bad
        return ".".join(result)

    return st.tuples(
        st.integers(min_value=0, max_value=3),
        st.tuples(good_octet, good_octet, good_octet, good_octet),
        bad_octet,
    ).map(_build)


_invalid_ip_strategy = st.one_of(
    _non_string_strategy,
    _ip_wrong_part_count(),
    _ip_non_digit_octet(),
    _ip_octet_out_of_range(),
)


# ---------------------------------------------------------------------------
# Port strategies
# ---------------------------------------------------------------------------
#
# A port is malformed when it is:
#   (a) not a string, or
#   (b) a string containing non-digits (incl. empty / signed / float / spaced),
#   (c) a decimal-digit string parsing to ``<= 0`` or ``> 65535``.


def _port_non_digit_string() -> st.SearchStrategy[str]:
    """Non-digit-only strings — covers empty, signed, alpha, float, spaced."""
    return st.one_of(
        st.just(""),                                                     # empty
        st.from_regex(r"\A[+-][0-9]+\Z", fullmatch=True),                # signed
        st.from_regex(r"\A[0-9]*[a-zA-Z][0-9a-zA-Z]*\Z", fullmatch=True),  # alpha
        st.text(
            alphabet=st.characters(blacklist_characters="0123456789"),
            min_size=1,
            max_size=8,
        ),
        st.from_regex(r"\A[0-9]+\.[0-9]+\Z", fullmatch=True),            # float-ish
        st.from_regex(r"\A +[0-9]+\Z", fullmatch=True),                  # space-prefixed
    )


def _port_out_of_range_string() -> st.SearchStrategy[str]:
    """Decimal-digit strings parsing to ``<= 0`` or ``> 65535``."""
    return st.one_of(
        # Zero is below the minimum (range is 1..65535 inclusive).
        st.from_regex(r"\A0+\Z", fullmatch=True),
        # 65536 .. 9_999_999_999 — strictly above the maximum.
        st.integers(min_value=65536, max_value=9_999_999_999).map(str),
    )


_invalid_port_strategy = st.one_of(
    _non_string_strategy,
    _port_non_digit_string(),
    _port_out_of_range_string(),
)


# ---------------------------------------------------------------------------
# UUID strategies
# ---------------------------------------------------------------------------
#
# A uuid is malformed when it is:
#   (a) not a string, or
#   (b) the empty string, or
#   (c) a string of length > 64.

_invalid_uuid_strategy = st.one_of(
    _non_string_strategy,
    st.just(""),
    st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=65,
        max_size=200,
    ),
)


# ---------------------------------------------------------------------------
# use_encryption strategies
# ---------------------------------------------------------------------------
#
# ``use_encryption`` is malformed when it is anything that is not a strict
# Python ``bool``. ``0`` and ``1`` are ``int`` (not ``bool``) so they are
# rejected; ``"true"``/``"false"`` are strings, also rejected; ``None``,
# lists, dicts, floats are all rejected.
_invalid_use_encryption_strategy = st.one_of(
    st.integers(min_value=-100, max_value=100),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.none(),
    st.text(max_size=10),
    st.lists(st.booleans(), max_size=3),
    st.dictionaries(st.text(min_size=1, max_size=3), st.booleans(), max_size=2),
).filter(lambda v: not isinstance(v, bool))


# ---------------------------------------------------------------------------
# Property 6 — one ``@given`` per key
# ---------------------------------------------------------------------------


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(bad_value=_invalid_ip_strategy)
def test_property6_invalid_ip_is_rejected_with_dotted_key(bad_value: Any) -> None:
    """Property 6 — ``input.kmbox_net.ip`` malformed values raise ``ConfigException``.

    For any ``bad_value`` produced by the curated invalid-IP strategy, the
    validator must raise ``ConfigException`` whose message contains the
    literal dotted key ``"input.kmbox_net.ip"``.
    """
    # Defense-in-depth filter: reject any string that happens to be a valid
    # dotted-quad. This guards against future strategy revisions that could
    # accidentally hit the valid space.
    if isinstance(bad_value, str):
        parts = bad_value.split(".")
        is_valid = (
            len(parts) == 4
            and all(
                p and p.isascii() and p.isdigit() and 0 <= int(p) <= 255
                for p in parts
            )
        )
        assume(not is_valid)

    cfg = _with_kmbox_value("ip", bad_value)
    with pytest.raises(
        ConfigException, match=re.escape("input.kmbox_net.ip")
    ):
        validate_kmbox_net_config(cfg)


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(bad_value=_invalid_port_strategy)
def test_property6_invalid_port_is_rejected_with_dotted_key(bad_value: Any) -> None:
    """Property 6 — ``input.kmbox_net.port`` malformed values raise ``ConfigException``.

    For any ``bad_value`` produced by the curated invalid-port strategy, the
    validator must raise ``ConfigException`` whose message contains the
    literal dotted key ``"input.kmbox_net.port"``.
    """
    # Defense-in-depth filter: reject any string that happens to be a valid
    # decimal-digit port in 1..65535.
    if isinstance(bad_value, str):
        is_valid = (
            bool(bad_value)
            and bad_value.isascii()
            and bad_value.isdigit()
            and 1 <= int(bad_value) <= 65535
        )
        assume(not is_valid)

    cfg = _with_kmbox_value("port", bad_value)
    with pytest.raises(
        ConfigException, match=re.escape("input.kmbox_net.port")
    ):
        validate_kmbox_net_config(cfg)


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(bad_value=_invalid_uuid_strategy)
def test_property6_invalid_uuid_is_rejected_with_dotted_key(bad_value: Any) -> None:
    """Property 6 — ``input.kmbox_net.uuid`` malformed values raise ``ConfigException``.

    For any ``bad_value`` produced by the curated invalid-UUID strategy
    (non-string, empty string, length-greater-than-64 string), the
    validator must raise ``ConfigException`` whose message contains the
    literal dotted key ``"input.kmbox_net.uuid"``.
    """
    # Defense-in-depth filter: the validator accepts any 1..64 length string;
    # filter out strategy outputs that fall inside that valid window.
    if isinstance(bad_value, str):
        assume(not (1 <= len(bad_value) <= 64))

    cfg = _with_kmbox_value("uuid", bad_value)
    with pytest.raises(
        ConfigException, match=re.escape("input.kmbox_net.uuid")
    ):
        validate_kmbox_net_config(cfg)


@pytest.mark.unit
@_PROPERTY_SETTINGS
@given(bad_value=_invalid_use_encryption_strategy)
def test_property6_invalid_use_encryption_is_rejected_with_dotted_key(
    bad_value: Any,
) -> None:
    """Property 6 — ``input.kmbox_net.use_encryption`` non-bool values raise.

    For any ``bad_value`` produced by the curated invalid-bool strategy
    (anything for which ``isinstance(v, bool)`` is ``False`` — including
    ``0``, ``1``, ``"true"``, ``None``, lists, dicts), the validator must
    raise ``ConfigException`` whose message contains the literal dotted key
    ``"input.kmbox_net.use_encryption"``.
    """
    # Defense-in-depth filter: ensure no ``bool`` slipped through the strategy.
    assume(not isinstance(bad_value, bool))

    cfg = _with_kmbox_value("use_encryption", bad_value)
    with pytest.raises(
        ConfigException,
        match=re.escape("input.kmbox_net.use_encryption"),
    ):
        validate_kmbox_net_config(cfg)
