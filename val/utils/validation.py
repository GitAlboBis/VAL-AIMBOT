"""
Input validation utilities for critical paths.

This module provides validation functions for common input validation patterns
across the framework, ensuring invalid data cannot cause crashes or undefined
behavior.

Runtime validators (``validate_frame``, ``validate_coordinates``,
``validate_delta_time``) raise :class:`ValidationException` on failure, which
should be caught at the validation point, logged, and handled with safe
defaults.

The configuration validator (``validate_target_configuration``) raises
:class:`ConfigException` on failure. It is meant to be called by the
Config_Loader in ``config.py`` and is NOT recoverable at runtime: an
unsupported value in ``config.yaml`` indicates a misconfiguration that must
be fixed before the framework can start.
"""

import logging
from typing import Any, Optional, Tuple

import numpy as np

from exceptions import ConfigException, ValidationException


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Target_Configuration (single source of truth used by the Config_Loader and
# by ``validate_target_configuration`` below). Kept as a local module-level
# constant — duplicating the dict in ``config.py`` — to avoid a circular
# import (``config.py`` already imports from this module). The two
# definitions MUST stay in sync; see design.md section M4.
# ---------------------------------------------------------------------------
TARGET_CONFIGURATION = {
    "general.architecture": "dual_pc",
    "capture.backend": "capture_card",
    "general.primary_engine": "ai",
    "input.driver": "kmbox_net",
}


def validate_frame(
    frame: Optional[np.ndarray],
    expected_shape: Optional[Tuple[int, int]] = None
) -> None:
    """
    Validate frame is not None, has correct shape and dtype.
    
    Ensures frame data is valid before processing by the AI engine or other
    components that expect properly formatted image data.
    
    Args:
        frame: Frame to validate (expected to be HxWx3 uint8 numpy array)
        expected_shape: Expected (height, width) tuple, or None to skip shape check
    
    Raises:
        ValidationException: If frame is None, wrong type, wrong dtype, wrong shape,
                           or doesn't match expected_shape
    
    Example:
        >>> frame = capture.grab_frame()
        >>> try:
        ...     validate_frame(frame, expected_shape=(640, 640))
        ...     result = ai_engine.process(frame)
        ... except ValidationException as e:
        ...     logger.warning(f"Invalid frame: {e}")
        ...     result = None
    """
    if frame is None:
        raise ValidationException("Frame is None")
    
    if not isinstance(frame, np.ndarray):
        raise ValidationException(f"Frame must be np.ndarray, got {type(frame).__name__}")
    
    if frame.dtype != np.uint8:
        raise ValidationException(f"Frame must be uint8, got {frame.dtype}")
    
    if len(frame.shape) != 3 or frame.shape[2] != 3:
        raise ValidationException(
            f"Frame must be HxWx3 (height, width, channels), got shape {frame.shape}"
        )
    
    if expected_shape is not None:
        h, w = expected_shape
        if frame.shape[0] != h or frame.shape[1] != w:
            raise ValidationException(
                f"Frame shape {frame.shape[:2]} does not match expected {expected_shape}"
            )


def validate_coordinates(
    x: float,
    y: float,
    max_x: float,
    max_y: float
) -> None:
    """
    Validate coordinates are not NaN and within bounds.
    
    Ensures target coordinates are valid before aim calculation or other
    operations that require valid screen positions.
    
    Args:
        x: X coordinate to validate
        y: Y coordinate to validate
        max_x: Maximum valid X coordinate (screen width or FOV width)
        max_y: Maximum valid Y coordinate (screen height or FOV height)
    
    Raises:
        ValidationException: If coordinates contain NaN or are out of bounds
    
    Example:
        >>> target_x, target_y = detection.get_center()
        >>> try:
        ...     validate_coordinates(target_x, target_y, screen_width, screen_height)
        ...     aim_controller.calculate_aim(True, (target_x, target_y))
        ... except ValidationException as e:
        ...     logger.warning(f"Invalid coordinates: {e}")
        ...     aim_controller.calculate_aim(False, (0, 0))
    """
    if np.isnan(x) or np.isnan(y):
        raise ValidationException(f"Coordinates contain NaN: ({x}, {y})")
    
    if x < 0 or x > max_x or y < 0 or y > max_y:
        raise ValidationException(
            f"Coordinates ({x}, {y}) out of bounds (0-{max_x}, 0-{max_y})"
        )


def validate_delta_time(
    dt: float,
    max_dt: float = 1.0
) -> None:
    """
    Validate delta time is positive and reasonable.
    
    Ensures time delta values are valid before physics calculations, smoothing,
    or other time-dependent operations.
    
    Args:
        dt: Delta time in seconds to validate
        max_dt: Maximum reasonable delta time in seconds (default: 1.0s)
    
    Raises:
        ValidationException: If delta time is non-positive or exceeds max_dt
    
    Example:
        >>> dt = time.perf_counter() - last_time
        >>> try:
        ...     validate_delta_time(dt, max_dt=0.1)
        ...     movement = calculate_movement(velocity, dt)
        ... except ValidationException as e:
        ...     logger.warning(f"Invalid delta time: {e}")
        ...     movement = 0.0
    """
    if dt <= 0:
        raise ValidationException(f"Delta time must be positive, got {dt}")
    
    if dt > max_dt:
        raise ValidationException(
            f"Delta time {dt}s exceeds maximum {max_dt}s (possible timer issue)"
        )


# ---------------------------------------------------------------------------
# Target configuration validator
# ---------------------------------------------------------------------------

_MISSING = object()


def _get_dotted(config: Any, dotted_key: str) -> Any:
    """
    Walk ``config`` following a dotted key path (e.g. ``"general.architecture"``).
    
    Returns the value found at ``dotted_key`` or the sentinel ``_MISSING`` if
    any segment of the path is absent or traverses a non-mapping value. This
    helper performs no type coercion and never raises.
    """
    current: Any = config
    for segment in dotted_key.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def validate_target_configuration(config: dict) -> None:
    """
    Verify that ``config`` matches the Target_Configuration.
    
    The Target_Configuration is the single hardware profile this build
    supports: ``general.architecture = dual_pc``,
    ``capture.backend = capture_card``, ``general.primary_engine = ai``,
    ``input.driver = kmbox_net``. Any other value for these four keys is
    considered unsupported.
    
    The Config_Loader is expected to apply target defaults for the four keys
    listed above BEFORE calling this validator (see design.md section C3),
    so a missing key here indicates an internal inconsistency and is still
    reported as an error.
    
    Args:
        config: Parsed ``config.yaml`` as a nested dict.
    
    Raises:
        ConfigException: If any of the four target keys has an unsupported
            value or is missing. The message always contains both the dotted
            key name and the offending (or missing) value so the user can
            correct ``config.yaml`` directly.
    
    Example:
        >>> cfg = {"general": {"architecture": "single_pc"}, ...}
        >>> validate_target_configuration(cfg)
        Traceback (most recent call last):
            ...
        exceptions.ConfigException: Configuration key 'general.architecture'
        has unsupported value 'single_pc' (expected 'dual_pc')
    """
    if not isinstance(config, dict):
        raise ConfigException(
            f"Configuration must be a mapping, got {type(config).__name__}"
        )

    for dotted_key, expected_value in TARGET_CONFIGURATION.items():
        actual_value = _get_dotted(config, dotted_key)

        if actual_value is _MISSING:
            raise ConfigException(
                f"Configuration key '{dotted_key}' is missing "
                f"(expected '{expected_value}')"
            )

        if actual_value != expected_value:
            raise ConfigException(
                f"Configuration key '{dotted_key}' has unsupported value "
                f"{actual_value!r} (expected '{expected_value}')"
            )


# ---------------------------------------------------------------------------
# KmBox Net configuration validator
# ---------------------------------------------------------------------------
#
# The KmBox_Net_Driver expects a specific shape under ``input.kmbox_net.*``.
# Per Req 3.7-3.10, malformed or missing values are hard errors: the loader
# names the offending dotted key and the offending value, and never silently
# falls back to a default. The four helpers below implement the validator
# table from design.md (one helper per key) and share a uniform error format.

# Whitelist of accepted ``input.kmbox_net.*`` keys, declared once so the
# validator and any future tooling can iterate over it without drift.
_KMBOX_NET_KEYS = ("ip", "port", "uuid", "use_encryption")


def _kmbox_error(dotted_key: str, value: Any, reason: str) -> ConfigException:
    """
    Build a uniformly-formatted ``ConfigException`` for a malformed
    ``input.kmbox_net.*`` value.

    The message format ``{dotted_key}={value!r}: <reason>`` puts the offending
    dotted key at the start of the message so the user can grep for it
    directly and so Property 6's ``pytest.raises(..., match=<dotted-key>)``
    assertion succeeds against the exception text.
    """
    return ConfigException(f"{dotted_key}={value!r}: {reason}")


def _require_ipv4_dotted_quad(section: dict, dotted_key: str) -> None:
    """
    Reject anything that is not a four-octet dotted-quad IPv4 string.

    Each octet must be a sequence of decimal digits parsing to an integer in
    ``0..255`` inclusive. Leading ``+``/``-`` signs, internal whitespace, and
    non-decimal digit characters are rejected. The full string ``str.split(".")``
    must yield exactly four segments.
    """
    leaf = dotted_key.rsplit(".", 1)[-1]
    if leaf not in section:
        raise _kmbox_error(dotted_key, None, "missing required key")

    value = section[leaf]
    if not isinstance(value, str):
        raise _kmbox_error(
            dotted_key, value,
            f"expected str (IPv4 dotted-quad), got {type(value).__name__}"
        )

    octets = value.split(".")
    if len(octets) != 4:
        raise _kmbox_error(
            dotted_key, value,
            f"expected 4 dot-separated octets, got {len(octets)}"
        )

    for index, octet in enumerate(octets):
        # ``str.isdigit`` rejects empty strings, signs, and non-decimal digits
        # (including unicode digit characters that ``int(...)`` would accept).
        if not octet or not octet.isdigit() or not octet.isascii():
            raise _kmbox_error(
                dotted_key, value,
                f"octet #{index + 1} {octet!r} is not a decimal-digit string"
            )

        octet_int = int(octet)
        if octet_int < 0 or octet_int > 255:
            raise _kmbox_error(
                dotted_key, value,
                f"octet #{index + 1} {octet_int} out of range 0..255"
            )


def _require_port_string(section: dict, dotted_key: str) -> None:
    """
    Reject anything that is not a decimal-digit string parsing to an integer
    in ``1..65535`` inclusive. Leading signs, whitespace (leading, trailing,
    or embedded), and leading zeros are rejected so the YAML loader's
    quoted-string form ``'6234'`` is the only accepted shape.

    Per kmbox-net-arm64-udp Req 11.3: the value must contain only ASCII
    decimal digits, with no leading zeros (``"06234"`` is rejected) and no
    whitespace anywhere in the string.
    """
    leaf = dotted_key.rsplit(".", 1)[-1]
    if leaf not in section:
        raise _kmbox_error(dotted_key, None, "missing required key")

    value = section[leaf]
    if not isinstance(value, str):
        raise _kmbox_error(
            dotted_key, value,
            f"expected str (decimal-digit port), got {type(value).__name__}"
        )

    if not value or not value.isdigit() or not value.isascii():
        raise _kmbox_error(
            dotted_key, value,
            "expected non-empty decimal-digit string"
        )

    # Per Req 11.3: reject leading zeros. ``"0"`` itself is also rejected by
    # the range check below (port must be in 1..65535), but a multi-digit
    # value with a leading zero (e.g. ``"06234"``) must fail with a leading-
    # zero diagnostic before any range check, since the integer value would
    # otherwise look in-range.
    if len(value) > 1 and value[0] == "0":
        raise _kmbox_error(
            dotted_key, value,
            "leading zeros are not allowed"
        )

    port_int = int(value)
    if port_int < 1 or port_int > 65535:
        raise _kmbox_error(
            dotted_key, value,
            f"port {port_int} out of range 1..65535"
        )


def _require_uuid_1_to_64(section: dict, dotted_key: str) -> None:
    """
    Reject anything that is not a string of length ``1..64`` inclusive. The
    vendor ``kmNet`` API accepts arbitrary non-empty token text for the UUID,
    so no format check beyond length is performed here.

    Per kmbox-net-arm64-udp Req 11.4: leading and trailing whitespace are
    additionally rejected so that ``" abc "`` does not silently pass even
    though its length is in range.
    """
    leaf = dotted_key.rsplit(".", 1)[-1]
    if leaf not in section:
        raise _kmbox_error(dotted_key, None, "missing required key")

    value = section[leaf]
    if not isinstance(value, str):
        raise _kmbox_error(
            dotted_key, value,
            f"expected str (1..64 chars), got {type(value).__name__}"
        )

    length = len(value)
    if length < 1 or length > 64:
        raise _kmbox_error(
            dotted_key, value,
            f"length {length} not in 1..64"
        )

    # Per Req 11.4: reject any leading or trailing whitespace. ``str.strip``
    # removes ASCII whitespace plus the broader Unicode whitespace set, which
    # is the most permissive interpretation that catches values such as
    # ``"\tabc"`` or ``"abc "`` produced by hand-edited YAML.
    if value != value.strip():
        raise _kmbox_error(
            dotted_key, value,
            "leading or trailing whitespace is not allowed"
        )


def _require_bool(section: dict, dotted_key: str) -> None:
    """
    Reject anything that is not a strict ``bool``. ``isinstance`` matches
    are used explicitly because ``bool`` is a subclass of ``int`` in Python:
    a literal ``0``/``1`` would otherwise duck-type as a boolean. Strings
    such as ``"true"`` are rejected for the same reason.
    """
    leaf = dotted_key.rsplit(".", 1)[-1]
    if leaf not in section:
        raise _kmbox_error(dotted_key, None, "missing required key")

    value = section[leaf]
    # NB: ``bool`` is a subclass of ``int``; a bare ``isinstance(v, int)`` check
    # would accept ``True``/``False``. The explicit ``isinstance(v, bool)``
    # check below is what rejects ``0``, ``1``, and ``"true"``.
    if not isinstance(value, bool):
        raise _kmbox_error(
            dotted_key, value,
            f"expected bool, got {type(value).__name__}"
        )


def validate_kmbox_net_config(config: dict) -> None:
    """
    Validate the ``input.kmbox_net.*`` block of a parsed ``config.yaml``.

    Enforces the type and range rules defined by spec
    ``kmbox-net-arm64-udp`` Req 11.1-11.5 (a strict superset of the original
    ``kmbox-net-integration`` Req 3.7-3.10 rules):

    - ``input.kmbox_net.ip`` (Req 11.2) is a string of four ASCII decimal
      octets separated by dots, each in ``0..255``, with no whitespace and
      no characters other than ASCII digits and the dot separator.
    - ``input.kmbox_net.port`` (Req 11.3) is a string of ASCII decimal
      digits parsing to an integer in ``1..65535`` with no whitespace and
      no leading zeros.
    - ``input.kmbox_net.uuid`` (Req 11.4) is a non-empty string of length
      ``1..64`` with no leading or trailing whitespace.
    - ``input.kmbox_net.use_encryption`` (Req 11.5) is a strict ``bool`` —
      ``yes``/``no``/``on``/``off``/``0``/``1``/``"true"``/``"false"`` are
      rejected.

    The four keys are validated in the fixed order
    ``ip → port → uuid → use_encryption`` per Req 11.1, and on the first
    failure exactly one ``ConfigException`` is raised whose message names
    the full dotted key path; subsequent keys are not validated (Req 11.11).

    A missing ``input.kmbox_net`` mapping is a hard error: the loader names
    the section in the exception message rather than silently filling in
    defaults.

    Args:
        config: Parsed ``config.yaml`` as a nested dict.

    Raises:
        ConfigException: If ``input.kmbox_net`` is missing, not a mapping, or
            contains any malformed value. The dotted key (and value where
            applicable) is always present in the message so callers and
            tests can assert against it via
            ``pytest.raises(ConfigException, match=<dotted-key>)``.

    Example:
        >>> validate_kmbox_net_config({
        ...     "input": {
        ...         "kmbox_net": {
        ...             "ip": "192.168.2.188",
        ...             "port": "6234",
        ...             "uuid": "00000000-0000-0000-0000-000000000000",
        ...             "use_encryption": True,
        ...         }
        ...     }
        ... })
    """
    if not isinstance(config, dict):
        raise ConfigException(
            f"Configuration must be a mapping, got {type(config).__name__}"
        )

    input_section = config.get("input")
    if input_section is None:
        raise ConfigException(
            "input.kmbox_net: missing required section 'input'"
        )
    if not isinstance(input_section, dict):
        raise ConfigException(
            f"input: expected mapping, got {type(input_section).__name__}"
        )

    # Detect the missing-section case explicitly so the error names
    # ``input.kmbox_net`` rather than the per-key leaf.
    if "kmbox_net" not in input_section:
        raise ConfigException(
            "input.kmbox_net: missing required section"
        )

    section = input_section["kmbox_net"]
    if not isinstance(section, dict):
        raise ConfigException(
            f"input.kmbox_net: expected mapping, got {type(section).__name__}"
        )

    _require_ipv4_dotted_quad(section, "input.kmbox_net.ip")
    _require_port_string(section, "input.kmbox_net.port")
    _require_uuid_1_to_64(section, "input.kmbox_net.uuid")
    _require_bool(section, "input.kmbox_net.use_encryption")


# ---------------------------------------------------------------------------
# Execution-provider value validator
# ---------------------------------------------------------------------------
#
# The ``ai_engine.execution_provider`` config key (npu-qnn-provider Req 4.1)
# selects which ONNX Runtime execution provider the engine pins to. The
# validator below enforces the schema described by Reqs 4.1 / 4.6 / 4.9:
#
# - List/dict values are a schema conflict and raise ``ConfigException``
#   (Req 4.9 — fail loudly so a malformed config does not silently degrade
#   the EP_Selector to ``auto``).
# - Non-string scalars are rejected with ``ConfigException`` for the same
#   reason.
# - String values are normalized via ``raw.strip().lower()`` and accepted
#   when they are members of ``_ALLOWED_EPS``.
# - Unknown string values emit a WARN naming the offending value and fall
#   back to ``"auto"`` (Req 4.6) so a fat-finger never aborts the engine.

_ALLOWED_EPS = {"auto", "qnn", "directml", "cpu"}


def validate_execution_provider_value(raw: Any) -> str:
    """
    Validate and normalize an ``ai_engine.execution_provider`` config value.

    Returns the canonical lowercase form of ``raw`` when it is one of
    ``{"auto", "qnn", "directml", "cpu"}``; falls back to ``"auto"`` with a
    WARN log when ``raw`` is a string outside that set; and raises
    :class:`ConfigException` when ``raw`` is structurally wrong (a ``list``,
    a ``dict``, or any non-string scalar).

    Args:
        raw: The value loaded from ``config.yaml`` under
            ``ai_engine.execution_provider``. Expected to be a string; any
            other shape is treated as a schema conflict.

    Returns:
        The normalized execution-provider name. Always one of
        ``{"auto", "qnn", "directml", "cpu"}``.

    Raises:
        ConfigException: If ``raw`` is a ``list``, a ``dict``, or any
            non-string scalar (Req 4.9). The message names the offending
            value and its type.

    Example:
        >>> validate_execution_provider_value("AUTO")
        'auto'
        >>> validate_execution_provider_value(" qnn ")
        'qnn'
        >>> validate_execution_provider_value("hexagon")  # logs WARN
        'auto'
        >>> validate_execution_provider_value(["qnn"])
        Traceback (most recent call last):
            ...
        exceptions.ConfigException: ai_engine.execution_provider=['qnn']: ...
    """
    # Reject list/dict explicitly so the message names the schema conflict
    # (Req 4.9 — these are the YAML shapes most likely to be confused with a
    # scalar string by hand-edited configs). ``bool`` is a subclass of
    # ``int`` in Python; the ``isinstance(raw, str)`` check below naturally
    # rejects booleans without a separate branch.
    if isinstance(raw, (list, dict)):
        raise ConfigException(
            f"ai_engine.execution_provider={raw!r}: expected scalar string, "
            f"got {type(raw).__name__} (schema conflict)"
        )

    if not isinstance(raw, str):
        raise ConfigException(
            f"ai_engine.execution_provider={raw!r}: expected str, "
            f"got {type(raw).__name__}"
        )

    normalized = raw.strip().lower()
    if normalized in _ALLOWED_EPS:
        return normalized

    # Unknown string → WARN + fall back to "auto" (Req 4.6). The offending
    # value is preserved verbatim in the log so the operator can see what
    # was misspelled.
    logger.warning(
        "ai_engine.execution_provider=%r unrecognized; falling back to 'auto' "
        "(allowed values: %s)",
        raw,
        sorted(_ALLOWED_EPS),
    )
    return "auto"


# ---------------------------------------------------------------------------
# aim.* and operator_override.* validators (aim-pipeline-simplification task 3.7)
# ---------------------------------------------------------------------------
#
# Per ``bugfix.md`` § 2.8 / 2.9 / 2.12 and the aim-pipeline-simplification
# design, the simplified aim pipeline reads exactly four numeric ``aim.*``
# keys (``pixel_to_count``, ``lock_radius_px``, ``lock_timeout_s``,
# ``max_fov_radius``) and three ``operator_override.*`` keys
# (``enabled``, ``threshold_counts``, ``window_ms``). Each must be present
# and strictly positive (the booleans being the obvious exception); a
# missing key or a non-positive value is a hard error so a hand-edited
# config never silently degrades the ONE pixel→count scaling stage
# (req 2.8) or the operator-override gate (req 2.9).
#
# The two validators below are called from :func:`config.load_config`
# immediately after :func:`validate_kmbox_net_config`. The four
# Target_Configuration keys / four ``input.kmbox_net.*`` keys remain
# untouched so preservation property P2.5 (req 3.10) keeps holding.


def _require_positive_number(
    section: dict, leaf_key: str, dotted_key: str
) -> float:
    """
    Reject anything that is not a strictly positive ``int`` or ``float``.

    Booleans are rejected explicitly — Python treats ``bool`` as a
    subclass of ``int`` so a literal ``True`` would otherwise duck-type
    as ``1.0``. ``NaN`` and ``±inf`` are rejected via the comparison
    chain ``value > 0``: ``NaN > 0`` is ``False`` and ``-inf > 0`` is
    ``False``; ``+inf > 0`` is ``True`` so we additionally reject
    non-finite floats.

    Returns the value as a ``float`` on success so the caller can use
    it without re-coercing.
    """
    if leaf_key not in section:
        raise ConfigException(f"{dotted_key}: missing required key")

    value = section[leaf_key]

    # ``bool`` is a subclass of ``int``; reject it explicitly.
    if isinstance(value, bool):
        raise ConfigException(
            f"{dotted_key}={value!r}: expected positive number, got bool"
        )

    if not isinstance(value, (int, float)):
        raise ConfigException(
            f"{dotted_key}={value!r}: expected positive number, "
            f"got {type(value).__name__}"
        )

    # Reject NaN and ±inf (only floats can be non-finite).
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ConfigException(
                f"{dotted_key}={value!r}: expected finite positive number"
            )

    if value <= 0:
        raise ConfigException(
            f"{dotted_key}={value!r}: expected > 0"
        )

    return float(value)


def _require_positive_int(
    section: dict, leaf_key: str, dotted_key: str
) -> int:
    """
    Reject anything that is not a strictly positive ``int``.

    Booleans (``True`` / ``False``) and floats are rejected explicitly so
    that ``threshold_counts`` and ``window_ms`` are exact integer counts.
    """
    if leaf_key not in section:
        raise ConfigException(f"{dotted_key}: missing required key")

    value = section[leaf_key]

    if isinstance(value, bool):
        raise ConfigException(
            f"{dotted_key}={value!r}: expected positive int, got bool"
        )

    if not isinstance(value, int):
        raise ConfigException(
            f"{dotted_key}={value!r}: expected positive int, "
            f"got {type(value).__name__}"
        )

    if value <= 0:
        raise ConfigException(
            f"{dotted_key}={value!r}: expected > 0"
        )

    return value


def validate_aim_config(config: dict) -> None:
    """
    Validate the ``aim.*`` block of a parsed ``config.yaml``.

    Enforces (per ``bugfix.md`` §§ 2.5, 2.6, 2.8, 2.12 and the
    aim-pipeline-simplification design):

    - ``aim.pixel_to_count``  (req 2.8) — strictly positive number;
      the ONE explicit pixel → HID-count scaling factor read by
      ``aim/pipeline.py::_to_counts``.
    - ``aim.lock_radius_px``  (req 2.3) — strictly positive number;
      the sticky-lock radius (capture-frame px) used by
      ``_select_sticky``.
    - ``aim.lock_timeout_s``  (req 2.3) — strictly positive number
      (seconds); the sticky-lock timeout window.
    - ``aim.max_fov_radius``  (req 2.3, 3.12) — strictly positive
      number (capture-frame px); the FOV-radius filter.

    A missing ``aim`` section, a missing key, or a non-positive value
    raises :class:`ConfigException` whose message names the offending
    dotted key path and value so the operator can correct
    ``config.yaml`` directly. No defaults are applied: the loader is
    responsible for a complete ``aim.*`` block.

    Args:
        config: Parsed ``config.yaml`` as a nested dict.

    Raises:
        ConfigException: If ``aim`` is missing, not a mapping, or any
            of the four required keys is missing or non-positive.
    """
    if not isinstance(config, dict):
        raise ConfigException(
            f"Configuration must be a mapping, got {type(config).__name__}"
        )

    aim_section = config.get("aim")
    if aim_section is None:
        raise ConfigException("aim: missing required section")
    if not isinstance(aim_section, dict):
        raise ConfigException(
            f"aim: expected mapping, got {type(aim_section).__name__}"
        )

    _require_positive_number(aim_section, "pixel_to_count", "aim.pixel_to_count")
    _require_positive_number(aim_section, "lock_radius_px", "aim.lock_radius_px")
    _require_positive_number(aim_section, "lock_timeout_s", "aim.lock_timeout_s")
    _require_positive_number(aim_section, "max_fov_radius", "aim.max_fov_radius")


def validate_operator_override_config(config: dict) -> None:
    """
    Validate the ``operator_override.*`` block of a parsed ``config.yaml``.

    Enforces (per ``bugfix.md`` § 2.9 and the aim-pipeline-simplification
    design):

    - ``operator_override.threshold_counts`` — strictly positive ``int``
      (HID mouse-counts); the operator-input displacement floor that
      breaks the lock.
    - ``operator_override.window_ms`` — strictly positive ``int``
      (milliseconds); the sliding window over which displacement is
      accumulated.

    A missing ``operator_override`` section, a missing key, or a
    non-positive value raises :class:`ConfigException`.

    The ``operator_override.enabled`` key is intentionally NOT validated
    here for type — its presence is optional at this stage. If the key
    is present and not a ``bool``, the runtime loader will surface that
    via the type system; per req 2.9, what matters for safety is that
    the threshold and window are positive integers, since those are the
    values the override gate consumes.

    Args:
        config: Parsed ``config.yaml`` as a nested dict.

    Raises:
        ConfigException: If ``operator_override`` is missing, not a
            mapping, or any of the two required numeric keys is missing
            or non-positive.
    """
    if not isinstance(config, dict):
        raise ConfigException(
            f"Configuration must be a mapping, got {type(config).__name__}"
        )

    section = config.get("operator_override")
    if section is None:
        raise ConfigException(
            "operator_override: missing required section"
        )
    if not isinstance(section, dict):
        raise ConfigException(
            f"operator_override: expected mapping, "
            f"got {type(section).__name__}"
        )

    _require_positive_int(
        section, "threshold_counts", "operator_override.threshold_counts"
    )
    _require_positive_int(
        section, "window_ms", "operator_override.window_ms"
    )
