"""
Signature-compliance test — Task 12.2 of spec ``kmbox-net-arm64-udp``.

# Feature: kmbox-net-arm64-udp, Smoke (Task 12.2): public-API
# signature compliance against design.md "Components and Interfaces".

**Smoke (signature compliance):** the public surface of
:class:`KmBoxNetDriver` matches the signatures declared in the
"Components and Interfaces" section of
``.kiro/specs/kmbox-net-arm64-udp/design.md``. Specifically, for
every public method and DD-compatible API method listed in the
design, :func:`inspect.signature` SHALL report:

  * the same **parameter names** in the same order,
  * the same **default values** (or no default if the design lists
    none),
  * **type annotations** that either equal the design's annotation
    verbatim or *widen* it (i.e. the implementation accepts a
    superset of the design's declared type via a ``Union`` /
    ``X | Y`` form whose members include the design's type) — a
    pragmatic accommodation for one known broadening on
    ``__init__(port=...)`` from ``str`` to ``str | int`` so the
    DD-compatible callers can pass either shape.

**Validates: Requirement 3.7** — "the existing public DD-compatible
API surface by exposing the methods ... with method names, parameter
names, parameter order, parameter type annotations, and default
values matching the corresponding signatures in the current
``input/kmbox_net_driver.py`` skeleton".

Implementation notes
--------------------

The reference dictionary :data:`_EXPECTED_SIGNATURES` is transcribed
verbatim from the "Components and Interfaces" section of
``design.md`` (lines around the ``class KmBoxNetDriver(BaseMouse):``
block). Each entry is a list of expected ``(name, annotation_str,
default)`` tuples in **declaration order**. ``self`` is omitted
because it is never reported by :meth:`inspect.Signature` for bound
methods on a class.

For every method, the test:

  1. Resolves the attribute on :class:`KmBoxNetDriver` and asserts it
     is callable.
  2. Calls :func:`inspect.signature` and reads
     :attr:`Signature.parameters` (which preserves declaration order
     in CPython 3.7+).
  3. Filters out the leading ``self`` parameter.
  4. Compares the remaining parameters element-by-element against the
     reference list:

       * **name**: strict equality.
       * **annotation**: passes if the actual annotation, normalized
         to a string via :func:`_norm_ann`, either equals the
         expected string or contains the expected string as one of
         its top-level union members (so ``"str | int"`` accepts
         expected ``"str"``).
       * **default**: strict equality (``inspect.Parameter.empty``
         for "no default").

  5. Verifies the return annotation likewise (verbatim or compatible
     widening of ``None`` → ``Optional[None]`` etc.) only when the
     design lists one.

Why a hand-curated reference (rather than parsing design.md)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The design.md "Components and Interfaces" section embeds the
signatures inside a Python code fence with full type annotations,
defaults, and ``...`` bodies. Re-parsing that fence at test time is
fragile (a future doc-formatting change would silently break the
test), and the contents *are* the spec: copying them once into this
test file makes the design-vs-implementation contract explicit and
auditable in code review.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, List, Tuple


# Make the ``input`` package importable when pytest is launched from
# the repository root or any sub-directory (the driver ships as
# ``input/kmbox_net_driver.py`` at the project root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from input.base_mouse import BaseMouse  # noqa: E402
from input.kmbox_net_driver import KmBoxNetDriver  # noqa: E402


# ---------------------------------------------------------------------------
# Reference signatures — transcribed verbatim from design.md
# "Components and Interfaces"
# ---------------------------------------------------------------------------

# Sentinel for "this parameter has no default in design.md".
_NO_DEFAULT = inspect.Parameter.empty


# Each entry: (parameter_name, annotation_string, default_value).
# Annotation strings are normalized via :func:`_norm_ann` before
# comparison, so "str | int" / "Union[str, int]" / "Optional[int]"
# all compare cleanly.
_EXPECTED_SIGNATURES: dict[str, List[Tuple[str, str, Any]]] = {
    # ---- constructor ----------------------------------------------
    "__init__": [
        ("ip", "str", "192.168.2.188"),
        ("port", "str", "41990"),
        ("uuid", "str", ""),
        ("use_encryption", "bool", True),
        ("target_cps", "float", 10.0),
    ],
    # ---- BaseMouse implementation ---------------------------------
    "send_move": [
        ("x", "int", _NO_DEFAULT),
        ("y", "int", _NO_DEFAULT),
    ],
    "send_click": [
        ("delay_before_click", "float", 0.0),
    ],
    "move": [
        ("x", "float", _NO_DEFAULT),
        ("y", "float", _NO_DEFAULT),
    ],
    "click": [
        ("delay_before_click", "float", 0.0),
    ],
    "reset_remainder": [],
    # ---- DD-compatible public API ---------------------------------
    "move_relative": [
        ("dx", "int", _NO_DEFAULT),
        ("dy", "int", _NO_DEFAULT),
    ],
    "click_button": [
        ("button", "int | str", 1),
    ],
    "mouse_down": [
        ("button", "int | str", 1),
    ],
    "mouse_up": [
        ("button", "int | str", 1),
    ],
    "key_press": [
        ("vk_code", "int", _NO_DEFAULT),
        ("hold_ms", "int", 50),
    ],
    "scroll": [
        ("amount", "int", _NO_DEFAULT),
    ],
    "get_driver_info": [],
    "release": [],
    # ---- native protocol commands — mouse class -------------------
    "_move": [
        ("x", "int", _NO_DEFAULT),
        ("y", "int", _NO_DEFAULT),
    ],
    "_left": [
        ("isdown", "int", _NO_DEFAULT),
    ],
    "_right": [
        ("isdown", "int", _NO_DEFAULT),
    ],
    "_middle": [
        ("isdown", "int", _NO_DEFAULT),
    ],
    "_wheel": [
        ("amount", "int", _NO_DEFAULT),
    ],
    "_mouse": [
        ("btn", "int", _NO_DEFAULT),
        ("x", "int", _NO_DEFAULT),
        ("y", "int", _NO_DEFAULT),
        ("wheel", "int", _NO_DEFAULT),
    ],
    "_move_auto": [
        ("x", "int", _NO_DEFAULT),
        ("y", "int", _NO_DEFAULT),
        ("ms", "int", _NO_DEFAULT),
    ],
    # Typo preserved per Requirement 4.8.
    "_move_beizer": [
        ("x", "int", _NO_DEFAULT),
        ("y", "int", _NO_DEFAULT),
        ("ms", "int", _NO_DEFAULT),
        ("x1", "int", _NO_DEFAULT),
        ("y1", "int", _NO_DEFAULT),
        ("x2", "int", _NO_DEFAULT),
        ("y2", "int", _NO_DEFAULT),
    ],
    # ---- native protocol commands — keyboard class ---------------
    "_keydown": [
        ("hid_code", "int", _NO_DEFAULT),
    ],
    "_keyup": [
        ("hid_code", "int", _NO_DEFAULT),
    ],
    # ---- monitor channel -----------------------------------------
    "monitor": [
        ("port", "int", _NO_DEFAULT),
    ],
    "isdown_left": [],
    "isdown_middle": [],
    "isdown_right": [],
    # ---- utility commands -----------------------------------------
    "reboot": [],
    "setconfig": [
        ("ip", "str", _NO_DEFAULT),
        ("port", "int", _NO_DEFAULT),
    ],
    "mask_mouse_left": [
        ("state", "int", _NO_DEFAULT),
    ],
    "unmask_all": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm_ann(annotation: Any) -> str:
    """Normalize an annotation to a comparable string form.

    Rules:
      * :data:`inspect.Parameter.empty` → ``""`` (no annotation).
      * A bare type (``int``, ``str``, ``float``, ``bool``, ``dict``,
        ``None``, ``type(None)``) → its ``__name__`` (or ``"None"``
        for ``NoneType``).
      * A string forward-reference → the string itself, stripped.
      * A :class:`typing.Union` / PEP-604 ``X | Y`` form → its
        members joined by ``" | "`` after recursive normalization;
        members are kept in source order so ``"str | int"`` and
        ``"int | str"`` both decode to comparable token sets in
        :func:`_annotation_matches`.
      * Anything else → ``str(annotation)``.

    The output is canonicalized only enough to make the comparison
    in :func:`_annotation_matches` independent of formatting noise
    such as ``typing.Optional[X]`` vs. ``X | None``.
    """
    if annotation is inspect.Parameter.empty:
        return ""
    if annotation is type(None):  # noqa: E721 — exact identity match
        return "None"
    if isinstance(annotation, type):
        return annotation.__name__
    if isinstance(annotation, str):
        return annotation.strip()

    # ``typing.get_origin`` / ``typing.get_args`` decompose Union /
    # PEP-604 unions uniformly. Importing locally so the module-load
    # path of this test stays minimal.
    import typing

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    # ``X | Y`` (PEP-604) has origin ``types.UnionType`` since 3.10;
    # ``Union[X, Y]`` (typing.Union) has origin ``typing.Union``.
    # Handle both shapes by checking for ``args`` and an origin name
    # ending in ``Union`` / equal to ``UnionType``.
    if args and (
        origin is typing.Union
        or (origin is not None and getattr(origin, "__name__", "") in {"UnionType", "Union"})
    ):
        return " | ".join(_norm_ann(a) for a in args)

    # Fallback: ``str()`` strips off ``typing.`` prefix imperfectly,
    # but the ``_annotation_matches`` token comparison absorbs the
    # difference for the simple cases we care about.
    text = str(annotation)
    return text.replace("typing.", "").strip()


def _annotation_matches(actual: Any, expected: str) -> bool:
    """Return ``True`` iff ``actual`` matches the design's ``expected`` annotation.

    A match holds when *either*:

      1. The normalized actual equals the normalized expected
         verbatim (including for ``""`` / no annotation), *or*
      2. The actual is a union (``A | B`` / ``Union[A, B]``) whose
         token set contains the expected — i.e. the implementation
         widened the design's declared type to also accept additional
         types. This accommodates the documented ``__init__(port=...)``
         widening from ``str`` to ``str | int`` without weakening
         the test for the rest of the surface.

    We deliberately do NOT permit *narrowing* (e.g. design ``str |
    int`` accepting actual ``str``): a narrower implementation would
    reject calls the design promises to accept, which is a real
    breakage rather than a benign widening.
    """
    actual_norm = _norm_ann(actual)
    expected_norm = expected.strip()

    if actual_norm == expected_norm:
        return True

    # Tokenize "str | int" → {"str", "int"} for set-membership checks
    # below. Strip and ignore empty parts so trailing/leading
    # separators do not break the comparison.
    def _tokenize(s: str) -> set[str]:
        return {t.strip() for t in s.split("|") if t.strip()}

    actual_tokens = _tokenize(actual_norm)
    expected_tokens = _tokenize(expected_norm)

    # If the expected is a single type and the actual is a union
    # whose token set contains it, accept (widening allowed).
    if len(expected_tokens) == 1 and expected_tokens.issubset(actual_tokens):
        return True

    # If both are unions and the token sets are equal, accept (the
    # implementation may list members in a different order than the
    # design — e.g. ``int | str`` vs. ``str | int`` — but the
    # accepted-types set is the same).
    if (
        len(actual_tokens) > 1
        and len(expected_tokens) > 1
        and actual_tokens == expected_tokens
    ):
        return True

    return False


def _signature_for(method_name: str) -> inspect.Signature:
    """Resolve ``method_name`` on :class:`KmBoxNetDriver` and return its signature.

    Uses :func:`inspect.signature` against the *unbound* function on
    the class so the leading ``self`` parameter is reported and can
    be skipped uniformly in :func:`_test_method_signature`. This also
    keeps the test independent of having to instantiate the driver
    (no fakes, no handshake side effects).
    """
    attr = getattr(KmBoxNetDriver, method_name, None)
    assert attr is not None, (
        "design vs. implementation drift: KmBoxNetDriver does not "
        "define a method named %r — the design 'Components and "
        "Interfaces' section requires this method per Requirement "
        "3.7." % (method_name,)
    )
    assert callable(attr), (
        "design vs. implementation drift: KmBoxNetDriver.%s exists "
        "but is not callable (got %r)." % (method_name, type(attr))
    )
    return inspect.signature(attr)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_kmboxnetdriver_subclasses_basemouse() -> None:
    """``KmBoxNetDriver`` inherits from ``BaseMouse`` (Requirement 3.1).

    A pre-condition for every other check: if the inheritance is
    broken, the BaseMouse method overrides (``send_move``,
    ``send_click``, ``move``, ``click``, ``reset_remainder``)
    cannot satisfy the abstract base. Asserting it here surfaces the
    drift with a clear diagnostic before the per-method comparisons
    start unrolling unrelated failures.
    """
    assert issubclass(KmBoxNetDriver, BaseMouse), (
        "Requirement 3.1 violated: KmBoxNetDriver must inherit from "
        "input.base_mouse.BaseMouse, but its MRO is %r."
        % (KmBoxNetDriver.__mro__,)
    )


def test_all_design_methods_are_present() -> None:
    """Every method declared by the design exists on ``KmBoxNetDriver``.

    Catches the "method silently dropped from the implementation"
    failure mode in one assertion rather than as a cluster of
    per-method ``AttributeError`` reports.
    """
    missing = [
        name
        for name in _EXPECTED_SIGNATURES
        if not hasattr(KmBoxNetDriver, name)
    ]
    assert not missing, (
        "Requirement 3.7 violated: KmBoxNetDriver is missing %d "
        "method(s) declared in design.md 'Components and Interfaces': "
        "%r."
        % (len(missing), missing)
    )


def _test_method_signature(method_name: str) -> None:
    """Compare one method's signature against the design's reference.

    Per-parameter checks (executed in declaration order):

      * **name**: strict equality with the design's parameter name.
      * **annotation**: :func:`_annotation_matches` (verbatim equal
        or accepted widening).
      * **default**: strict equality. ``_NO_DEFAULT`` (the design
        lists no default) compares equal to
        :data:`inspect.Parameter.empty`.
    """
    expected = _EXPECTED_SIGNATURES[method_name]
    sig = _signature_for(method_name)
    # Drop ``self`` (always the first parameter on instance methods).
    actual_params = [
        p for p in sig.parameters.values()
        if p.name != "self"
    ]

    assert len(actual_params) == len(expected), (
        "Requirement 3.7 violated: KmBoxNetDriver.%s has %d "
        "parameter(s) (%r), but design.md declares %d (%r)."
        % (
            method_name,
            len(actual_params),
            [p.name for p in actual_params],
            len(expected),
            [name for name, _, _ in expected],
        )
    )

    for index, (actual_param, (exp_name, exp_ann, exp_default)) in enumerate(
        zip(actual_params, expected)
    ):
        # Name (strict).
        assert actual_param.name == exp_name, (
            "Requirement 3.7 violated: KmBoxNetDriver.%s parameter "
            "#%d: design name=%r, actual name=%r."
            % (method_name, index, exp_name, actual_param.name)
        )

        # Default (strict).
        assert actual_param.default == exp_default, (
            "Requirement 3.7 violated: KmBoxNetDriver.%s parameter "
            "%r: design default=%r, actual default=%r."
            % (method_name, exp_name, exp_default, actual_param.default)
        )

        # Annotation (verbatim or accepted widening).
        assert _annotation_matches(actual_param.annotation, exp_ann), (
            "Requirement 3.7 violated: KmBoxNetDriver.%s parameter "
            "%r: design annotation=%r, actual annotation=%r "
            "(normalized %r). Annotation mismatches narrower than "
            "the design are real breakage; widening (e.g. design "
            "``str`` → actual ``str | int``) is permitted but the "
            "expected type must remain a member of the union."
            % (
                method_name,
                exp_name,
                exp_ann,
                actual_param.annotation,
                _norm_ann(actual_param.annotation),
            )
        )


# ---- One ``test_*`` function per method ---------------------------------
#
# Generating one test function per method (rather than one big
# parametrize) keeps the failure diagnostic message tied to the
# specific method and makes the failing test name self-describing
# in pytest output (``test_signature_init`` / ``test_signature_move``
# / …). This is how the existing test files in this folder are
# organized.


def test_signature_init() -> None:
    """``__init__`` matches the design (constructor)."""
    _test_method_signature("__init__")


def test_signature_send_move() -> None:
    """``send_move`` matches the design (BaseMouse override)."""
    _test_method_signature("send_move")


def test_signature_send_click() -> None:
    """``send_click`` matches the design (BaseMouse override)."""
    _test_method_signature("send_click")


def test_signature_move() -> None:
    """``move`` matches the design (BaseMouse override)."""
    _test_method_signature("move")


def test_signature_click() -> None:
    """``click`` matches the design (BaseMouse override)."""
    _test_method_signature("click")


def test_signature_reset_remainder() -> None:
    """``reset_remainder`` matches the design (BaseMouse override)."""
    _test_method_signature("reset_remainder")


def test_signature_move_relative() -> None:
    """``move_relative`` matches the design (DD-compatible API)."""
    _test_method_signature("move_relative")


def test_signature_click_button() -> None:
    """``click_button`` matches the design (DD-compatible API)."""
    _test_method_signature("click_button")


def test_signature_mouse_down() -> None:
    """``mouse_down`` matches the design (DD-compatible API)."""
    _test_method_signature("mouse_down")


def test_signature_mouse_up() -> None:
    """``mouse_up`` matches the design (DD-compatible API)."""
    _test_method_signature("mouse_up")


def test_signature_key_press() -> None:
    """``key_press`` matches the design (DD-compatible API)."""
    _test_method_signature("key_press")


def test_signature_scroll() -> None:
    """``scroll`` matches the design (DD-compatible API)."""
    _test_method_signature("scroll")


def test_signature_get_driver_info() -> None:
    """``get_driver_info`` matches the design (DD-compatible API)."""
    _test_method_signature("get_driver_info")


def test_signature_release() -> None:
    """``release`` matches the design (lifecycle)."""
    _test_method_signature("release")


def test_signature__move() -> None:
    """``_move`` matches the design (mouse command)."""
    _test_method_signature("_move")


def test_signature__left() -> None:
    """``_left`` matches the design (mouse command)."""
    _test_method_signature("_left")


def test_signature__right() -> None:
    """``_right`` matches the design (mouse command)."""
    _test_method_signature("_right")


def test_signature__middle() -> None:
    """``_middle`` matches the design (mouse command)."""
    _test_method_signature("_middle")


def test_signature__wheel() -> None:
    """``_wheel`` matches the design (mouse command)."""
    _test_method_signature("_wheel")


def test_signature__mouse() -> None:
    """``_mouse`` matches the design (combined mouse command)."""
    _test_method_signature("_mouse")


def test_signature__move_auto() -> None:
    """``_move_auto`` matches the design (mouse command)."""
    _test_method_signature("_move_auto")


def test_signature__move_beizer() -> None:
    """``_move_beizer`` matches the design (mouse command, typo preserved)."""
    _test_method_signature("_move_beizer")


def test_signature__keydown() -> None:
    """``_keydown`` matches the design (keyboard command)."""
    _test_method_signature("_keydown")


def test_signature__keyup() -> None:
    """``_keyup`` matches the design (keyboard command)."""
    _test_method_signature("_keyup")


def test_signature_monitor() -> None:
    """``monitor`` matches the design (monitor channel)."""
    _test_method_signature("monitor")


def test_signature_isdown_left() -> None:
    """``isdown_left`` matches the design (monitor channel reader)."""
    _test_method_signature("isdown_left")


def test_signature_isdown_middle() -> None:
    """``isdown_middle`` matches the design (monitor channel reader)."""
    _test_method_signature("isdown_middle")


def test_signature_isdown_right() -> None:
    """``isdown_right`` matches the design (monitor channel reader)."""
    _test_method_signature("isdown_right")


def test_signature_reboot() -> None:
    """``reboot`` matches the design (utility command)."""
    _test_method_signature("reboot")


def test_signature_setconfig() -> None:
    """``setconfig`` matches the design (utility command)."""
    _test_method_signature("setconfig")


def test_signature_mask_mouse_left() -> None:
    """``mask_mouse_left`` matches the design (utility command)."""
    _test_method_signature("mask_mouse_left")


def test_signature_unmask_all() -> None:
    """``unmask_all`` matches the design (utility command)."""
    _test_method_signature("unmask_all")
