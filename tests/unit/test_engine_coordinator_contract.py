"""
Unit test — ``EngineCoordinator`` contract.

Originally written for single-config-streamlining task 13.2 (Req 4.8) to
pin the three-arg passive-façade signature of
:class:`engines.coordinator.EngineCoordinator` and to guard against
re-introduction of the removed HSV / memory-ESP engines.

Updated by the ``post-refactor-runtime-regressions`` bugfix spec
(``.kiro/specs/post-refactor-runtime-regressions``) to accept the
widened ``__init__`` signature: ``EngineCoordinator`` now also accepts
a single ``shared_state`` argument to match the call pattern in
``main.main()``. The rationale is recorded in that spec's ``design.md``
(§Fix Implementation / Bug 1); the change is intentional and narrowly
scoped to adding a new non-legacy entry point.

The legacy-rejection assertions are **preserved verbatim**:

1. ``__init__`` still accepts no ``hsv_engine`` / ``memory_esp``
   parameters (Req 4.8).
2. ``_engine_errors`` still tracks no ``'hsv'`` / ``'memory_esp'`` keys
   on either construction path (Req 4.8).
3. No instance attribute contains ``hsv`` or ``memory_esp`` in its name
   on either construction path (Req 4.8).

New assertions added by this spec:

4. ``EngineCoordinator(SharedState())`` succeeds and yields an instance
   with ``ai_engine = None``, ``target_tracker = None``, and
   ``_engine_errors == {'ai': 0}``.
5. The 3-arg form (positional and keyword) continues to work.

**Validates: Requirements 4.8 (single-config-streamlining),
2.1, 2.2, 3.1, 3.2 (post-refactor-runtime-regressions)**
"""

from __future__ import annotations

import inspect
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from engines.coordinator import EngineCoordinator
from gui.shared_state import SharedState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LEGACY_PARAM_NAMES = frozenset({'hsv_engine', 'memory_esp'})
LEGACY_ATTR_SUBSTRINGS = ('hsv', 'memory_esp')
LEGACY_ERROR_KEYS = frozenset({'hsv', 'memory_esp'})


def _make_coordinator() -> EngineCoordinator:
    """Instantiate an ``EngineCoordinator`` with lightweight mocks (3-arg form)."""
    ai_engine = MagicMock(name='AIVisionEngine')
    target_tracker = MagicMock(name='TargetTracker')
    config: Dict[str, Any] = {}
    return EngineCoordinator(
        ai_engine=ai_engine,
        target_tracker=target_tracker,
        config=config,
    )


def _make_coordinator_from_shared_state() -> EngineCoordinator:
    """Instantiate an ``EngineCoordinator`` from a fresh ``SharedState`` (1-arg form)."""
    return EngineCoordinator(SharedState())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEngineCoordinatorInitSignature:
    """Req 4.8: ``__init__`` has no legacy parameters.

    The signature is now dispatched (``*args, **kwargs``) to accept both
    the 1-arg shared-state form and the 3-arg engines form. We no longer
    pin the parameter list to a specific tuple — that was a proxy for
    "no legacy engine params", which is now asserted directly by name.
    """

    def test_init_has_no_legacy_parameters(self) -> None:
        """No ``hsv_engine`` / ``memory_esp`` parameters in ``__init__``.

        With the dispatched ``*args, **kwargs`` signature, positional
        names are no longer pinned, so we probe both the formal
        parameter list and the function's accepted keyword names by
        attempting a construction.
        """
        sig = inspect.signature(EngineCoordinator.__init__)
        leaked = LEGACY_PARAM_NAMES.intersection(sig.parameters.keys())

        assert not leaked, (
            f"EngineCoordinator.__init__ must not accept legacy parameters, "
            f"but found: {sorted(leaked)}"
        )

        # Probe: passing a legacy kwarg must be rejected (TypeError).
        for legacy_name in LEGACY_PARAM_NAMES:
            with pytest.raises(TypeError):
                EngineCoordinator(**{legacy_name: MagicMock()})

    def test_init_accepts_three_arg_positional_and_keyword_calls(self) -> None:
        """3-arg construction (single-config-streamlining Design C6) still works.

        Preservation baseline for the Bug 1 fix: widening ``__init__`` to
        also accept a single ``shared_state`` must not break the existing
        3-arg form, either positional or keyword.
        """
        ai_engine = MagicMock(name='AIVisionEngine')
        target_tracker = MagicMock(name='TargetTracker')
        config: Dict[str, Any] = {}

        # Positional form.
        coord_pos = EngineCoordinator(ai_engine, target_tracker, config)
        assert coord_pos.ai_engine is ai_engine
        assert coord_pos.target_tracker is target_tracker
        assert coord_pos.config is config

        # Keyword form.
        coord_kw = EngineCoordinator(
            ai_engine=ai_engine,
            target_tracker=target_tracker,
            config=config,
        )
        assert coord_kw.ai_engine is ai_engine
        assert coord_kw.target_tracker is target_tracker
        assert coord_kw.config is config

    def test_init_accepts_shared_state_positional_form(self) -> None:
        """``EngineCoordinator(shared_state)`` succeeds (post-refactor Bug 1).

        Replays ``main.main()``'s construction pattern. The coordinator
        pulls its config snapshot from the shared state and leaves
        ``ai_engine`` / ``target_tracker`` as ``None`` for the surrounding
        framework to attach later.
        """
        shared_state = SharedState()
        coord = EngineCoordinator(shared_state)

        assert coord.ai_engine is None, (
            "shared-state construction must leave ai_engine unset; "
            f"got {coord.ai_engine!r}"
        )
        assert coord.target_tracker is None, (
            "shared-state construction must leave target_tracker unset; "
            f"got {coord.target_tracker!r}"
        )
        assert coord.config == shared_state.get_config()
        assert coord._engine_errors == {'ai': 0}, (
            f"shared-state _engine_errors must be exactly {{'ai': 0}}; "
            f"got {coord._engine_errors!r}"
        )

    def test_init_accepts_shared_state_keyword_form(self) -> None:
        """``EngineCoordinator(shared_state=shared_state)`` succeeds.

        The keyword form is parametrised in the regressions exploration
        test; the contract must accept it alongside the positional form.
        """
        shared_state = SharedState()
        coord = EngineCoordinator(shared_state=shared_state)

        assert coord.ai_engine is None
        assert coord.target_tracker is None
        assert coord.config == shared_state.get_config()
        assert coord._engine_errors == {'ai': 0}


@pytest.mark.unit
class TestEngineCoordinatorEngineErrors:
    """Req 4.8: ``_engine_errors`` only has keys for engines still present."""

    def test_engine_errors_has_no_legacy_keys_three_arg_form(self) -> None:
        """Neither ``'hsv'`` nor ``'memory_esp'`` are keys of ``_engine_errors``."""
        coord = _make_coordinator()

        leaked_keys = LEGACY_ERROR_KEYS.intersection(coord._engine_errors.keys())
        assert not leaked_keys, (
            f"_engine_errors must not contain legacy engine keys, "
            f"but found: {sorted(leaked_keys)}"
        )

    def test_engine_errors_has_no_legacy_keys_shared_state_form(self) -> None:
        """Legacy-key prohibition also holds on the shared-state path."""
        coord = _make_coordinator_from_shared_state()

        leaked_keys = LEGACY_ERROR_KEYS.intersection(coord._engine_errors.keys())
        assert not leaked_keys, (
            f"_engine_errors (shared-state form) must not contain legacy "
            f"engine keys, but found: {sorted(leaked_keys)}"
        )

    def test_engine_errors_tracks_ai_engine_three_arg_form(self) -> None:
        """``_engine_errors`` exposes an ``'ai'`` counter initialized to 0."""
        coord = _make_coordinator()

        assert 'ai' in coord._engine_errors, (
            "_engine_errors must track the AI engine under key 'ai'"
        )
        assert coord._engine_errors['ai'] == 0, (
            f"_engine_errors['ai'] should start at 0, got {coord._engine_errors['ai']}"
        )

    def test_engine_errors_tracks_ai_engine_shared_state_form(self) -> None:
        """The ``'ai'`` counter is also initialized on the shared-state path."""
        coord = _make_coordinator_from_shared_state()

        assert 'ai' in coord._engine_errors
        assert coord._engine_errors['ai'] == 0

    def test_engine_errors_keys_are_subset_of_present_engines(self) -> None:
        """All keys in ``_engine_errors`` refer to engines still in the codebase.

        The design currently lists ``'ai'`` as the canonical entry; additional
        keys are allowed (e.g. for tracker/resolver) but none may reference
        removed engines.
        """
        for coord in (_make_coordinator(), _make_coordinator_from_shared_state()):
            allowed_prefixes = {
                'ai', 'target', 'aim', 'tracker', 'resolver', 'controller',
            }
            for key in coord._engine_errors:
                assert not any(
                    legacy in key.lower() for legacy in LEGACY_ATTR_SUBSTRINGS
                ), f"_engine_errors key '{key}' references a removed engine"
                assert (
                    any(key.startswith(prefix) for prefix in allowed_prefixes)
                    or key == 'ai'
                ), (
                    f"_engine_errors key '{key}' does not match any known "
                    f"present engine"
                )


@pytest.mark.unit
class TestEngineCoordinatorAttributes:
    """Req 4.8: no instance attribute whose name contains ``hsv`` or ``memory_esp``."""

    def test_no_instance_attribute_references_legacy_engines_three_arg_form(self) -> None:
        """Instance ``__dict__`` contains no legacy-named attributes (3-arg form)."""
        coord = _make_coordinator()

        offending = [
            name
            for name in vars(coord)
            if any(substr in name.lower() for substr in LEGACY_ATTR_SUBSTRINGS)
        ]

        assert not offending, (
            f"EngineCoordinator instance must not carry attributes named after "
            f"removed engines, but found: {offending}"
        )

    def test_no_instance_attribute_references_legacy_engines_shared_state_form(self) -> None:
        """Instance ``__dict__`` contains no legacy-named attributes (shared-state form)."""
        coord = _make_coordinator_from_shared_state()

        offending = [
            name
            for name in vars(coord)
            if any(substr in name.lower() for substr in LEGACY_ATTR_SUBSTRINGS)
        ]

        assert not offending, (
            f"EngineCoordinator (shared-state form) must not carry attributes "
            f"named after removed engines, but found: {offending}"
        )

    def test_no_class_attribute_references_legacy_engines(self) -> None:
        """Class-level attributes also do not expose legacy names.

        Inherited ``object`` dunders are skipped; only attributes defined on
        ``EngineCoordinator`` itself are inspected.
        """
        own_attrs = [
            name
            for name in vars(EngineCoordinator)
            if not (name.startswith('__') and name.endswith('__'))
        ]

        offending = [
            name
            for name in own_attrs
            if any(substr in name.lower() for substr in LEGACY_ATTR_SUBSTRINGS)
        ]

        assert not offending, (
            f"EngineCoordinator class must not define attributes named after "
            f"removed engines, but found: {offending}"
        )
