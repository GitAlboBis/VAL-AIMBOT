"""
Engine Coordinator — coordinates the remaining backend engines.

Post-refactoring scope (single-config-streamlining, Req 4.8 / Design C6):
- Owns a reference to the only engine still present in the Refactored_Codebase:
  `AIVisionEngine`.
- Exposes a hot-reload entry point (`update_config`) that forwards relevant
  configuration sections to the owned engine.
- Tracks per-engine error counters in `_engine_errors`. Only keys for engines
  that still exist in the codebase are present; no `'hsv'` or `'memory_esp'`
  entries.

Aim-pipeline-simplification update (req 2.13, 2.14, 4.4) — the legacy
``TargetTracker`` (2,633 lines) has been replaced by the stateless
``engines.hsv_tracker.pick_hsv_target`` function. The coordinator no
longer carries a ``target_tracker`` attribute; ``main.DetectionFramework``
calls ``pick_hsv_target`` inline from ``process_detections`` instead.
The 3-arg ``EngineCoordinator(ai_engine, target_tracker, config)``
construction shape is kept for backwards-compatibility with surviving
callers (the ``target_tracker`` slot is accepted as an opaque token and
not used at runtime).

Explicitly out of scope here (removed by this spec):
- HSV detection engine hooks (`engines.hsv_engine` is removed).
- Memory ESP hooks (`engines.memory_esp` is removed).
- `HSVEngineException` / `MemoryESPException` handling (removed from
  `exceptions.py`).

The legacy background-thread machinery (start/stop/engine_loop tied to
`SharedState`) has been dropped: it was coupled to removed engines and to
`SharedState`-based fallback logic. The runtime loop is owned by
`main.DetectionFramework` going forward.

Constructor dispatch (post-refactor-runtime-regressions, Bug 1):
``__init__`` is dispatched on its argument shape to support two call sites:

- ``EngineCoordinator(shared_state)`` — the pattern used by ``main.main()``
  (line 832). The coordinator reads the current config snapshot from the
  shared state and leaves ``ai_engine`` / ``target_tracker`` as ``None``;
  the surrounding ``main.DetectionFramework`` is responsible for wiring
  the real engines onto the coordinator later. ``update_config`` already
  guards ``self.ai_engine is not None`` / ``self.target_tracker is not
  None``, so an un-wired coordinator is a safe no-op.
- ``EngineCoordinator(ai_engine, target_tracker, config)`` — the 3-arg form
  introduced by single-config-streamlining Req 4.8 / Design C6. This form
  continues to work unchanged and is exercised by the contract test in
  ``tests/unit/test_engine_coordinator_contract.py``. After the
  aim-pipeline-simplification refactor the ``target_tracker`` slot is
  retained for signature compatibility but is treated as an opaque
  token: the coordinator stores it on ``self.target_tracker`` (so
  existing assertions still see the value they passed in) but never
  invokes any method on it, because ``TargetTracker`` no longer exists.

The passive-façade contract (Design C6) is preserved on both paths: no
thread is spawned, no frame loop is driven. ``start()`` / ``stop()`` are
documented no-ops that exist only to satisfy ``main.py``'s lifecycle call
pattern.
"""

import logging
from typing import Any, Dict, Optional

from engines.ai_engine import AIVisionEngine
from exceptions import AIEngineException, EngineException

logger = logging.getLogger(__name__)


def _looks_like_shared_state(obj: Any) -> bool:
    """Return True if *obj* quacks like a ``SharedState`` instance.

    We dispatch on structural type rather than an ``isinstance`` check to
    avoid importing ``gui.shared_state`` at module load time (the GUI
    package pulls in Tk / imgui dependencies that are expensive or
    unavailable in headless contexts).
    """
    return hasattr(obj, 'get_config') and callable(getattr(obj, 'get_config'))


class EngineCoordinator:
    """Coordinates the AI detection engine and the target tracker.

    The coordinator is a thin façade: it holds references to the owned
    engines and fans out configuration updates. It does not own a thread;
    the surrounding runtime (see `main.DetectionFramework`) drives frame
    processing directly.

    Attributes:
        ai_engine: The `AIVisionEngine` instance used for detection, or
            ``None`` when constructed from a shared state without engines
            attached yet.
        target_tracker: Legacy slot kept for the 3-arg construction shape
            (single-config-streamlining Design C6). Stored as an opaque
            token because ``TargetTracker`` was removed by the
            aim-pipeline-simplification refactor (req 2.13, 4.4). The
            coordinator never invokes any method on it; the HSV
            fallback now runs as a stateless ``pick_hsv_target`` call
            inside ``main.DetectionFramework.process_detections``.
        config: The last-known configuration dict. Used as a read-only
            snapshot; hot-reloads go through `update_config`.
        _engine_errors: Mapping from short engine key to error count. Only
            keys for engines still present in the Refactored_Codebase are
            kept; per Req 4.8 this contains neither `'hsv'` nor
            `'memory_esp'`.
        _shared_state: The ``SharedState`` instance the coordinator was
            constructed from, or ``None`` for the 3-arg form.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the coordinator.

        Two call shapes are supported:

        1. ``EngineCoordinator(shared_state)`` — single-arg form used by
           ``main.main()``. Reads ``shared_state.get_config()`` for the
           config snapshot and leaves ``ai_engine`` / ``target_tracker``
           as ``None`` (engine attachment is deferred to the surrounding
           framework). The ``shared_state`` kwarg form
           ``EngineCoordinator(shared_state=shared_state)`` is also
           accepted.
        2. ``EngineCoordinator(ai_engine, target_tracker, config)`` —
           the 3-arg form from single-config-streamlining Design C6.
           Positional and keyword forms are both accepted.

        Dispatch is by positional arg count combined with a structural
        type check: the single-arg form requires the first argument to
        expose ``get_config()`` (duck-typed ``SharedState``).

        Args:
            *args: Positional arguments. Either one ``SharedState`` or
                three engines/config values, see above.
            **kwargs: Keyword arguments. Accepted names are
                ``shared_state`` (single-arg form) or ``ai_engine`` /
                ``target_tracker`` / ``config`` (3-arg form).

        Raises:
            TypeError: If the argument combination doesn't match either
                supported shape.
        """
        shared_state: Optional[Any] = None
        ai_engine: Optional[AIVisionEngine] = None
        target_tracker: Optional[Any] = None
        config: Optional[Dict[str, Any]] = None

        # Flatten positional args into the named slots.
        total_args = len(args) + len(kwargs)

        if total_args == 1:
            # Single-arg form: shared_state either positional or keyword.
            if len(args) == 1:
                candidate = args[0]
            elif 'shared_state' in kwargs:
                candidate = kwargs['shared_state']
            else:
                # e.g. EngineCoordinator(config=...) — not a supported shape.
                raise TypeError(
                    "EngineCoordinator() with a single argument expects a "
                    "SharedState-like object (positional or shared_state=...); "
                    f"got kwargs={sorted(kwargs.keys())!r}"
                )
            if not _looks_like_shared_state(candidate):
                raise TypeError(
                    "EngineCoordinator() single-arg form requires a "
                    "SharedState-like object exposing .get_config(); got "
                    f"{type(candidate).__name__!r}"
                )
            shared_state = candidate

        elif total_args == 3:
            # 3-arg form: (ai_engine, target_tracker, config) — positional,
            # keyword, or any mix.
            try:
                ai_engine = kwargs.pop('ai_engine') if 'ai_engine' in kwargs else args[0]
                target_tracker = (
                    kwargs.pop('target_tracker') if 'target_tracker' in kwargs else args[1]
                )
                config = kwargs.pop('config') if 'config' in kwargs else args[2]
            except IndexError as exc:
                raise TypeError(
                    "EngineCoordinator() 3-arg form expects "
                    "(ai_engine, target_tracker, config); got "
                    f"args={args!r}, kwargs={sorted(kwargs.keys())!r}"
                ) from exc
            if kwargs:
                raise TypeError(
                    f"EngineCoordinator() got unexpected keyword arguments: "
                    f"{sorted(kwargs.keys())!r}"
                )

        else:
            raise TypeError(
                "EngineCoordinator() expects either 1 argument "
                "(shared_state) or 3 arguments "
                "(ai_engine, target_tracker, config); got "
                f"{total_args} argument(s)"
            )

        if shared_state is not None:
            # Single-arg / shared-state path.
            #
            # Engine attachment is intentionally deferred: constructing real
            # AIVisionEngine / TargetTracker instances here would require a
            # capture device and a model file, which is side-effectful and
            # not appropriate for the coordinator's passive-façade role.
            # `main.DetectionFramework` builds the engines as part of its
            # own initialize_engines() flow and attaches them onto the
            # coordinator there. `update_config` below already guards on
            # `self.ai_engine is not None` / `self.target_tracker is not
            # None`, so an un-wired coordinator safely no-ops on hot-reload.
            self._shared_state = shared_state
            self.ai_engine = None
            self.target_tracker = None
            self.config = shared_state.get_config()
        else:
            # 3-arg / engines path (single-config-streamlining Design C6).
            self._shared_state = None
            self.ai_engine = ai_engine
            self.target_tracker = target_tracker
            self.config = config if config is not None else {}

        # Error counters — only for engines still present in the Refactored_Codebase.
        # Req 4.8: no `'hsv'` or `'memory_esp'` entries. Initialized identically
        # on both construction paths.
        self._engine_errors: Dict[str, int] = {'ai': 0}

    def start(self) -> None:
        """No-op lifecycle hook.

        The coordinator is a **passive façade** (single-config-streamlining
        Design C6): it holds references and fans out configuration updates
        but does not own a thread or drive a frame loop. This method exists
        solely to satisfy the lifecycle call pattern in ``main.main()``
        (which invokes ``coordinator.start()`` after construction). It
        does not spawn any thread, does not start any loop, and returns
        immediately.
        """
        return None

    def stop(self) -> None:
        """No-op lifecycle hook.

        Companion to :meth:`start`. The coordinator is a **passive façade**
        (single-config-streamlining Design C6) and does not own any thread
        to halt. This method exists solely to satisfy the lifecycle call
        pattern in ``main.main()`` (which invokes ``coordinator.stop()``
        during shutdown). It does not halt any thread, does not tear down
        any resource, and returns immediately.
        """
        return None

    def update_config(self, config: Dict[str, Any]) -> None:
        """Apply a configuration change to the owned engines.

        Reads only the configuration sections relevant to the engines still
        present:

        - `ai_engine.*` → forwarded to `AIVisionEngine.update_config`.
        - `aim.aim_fov_x` / `aim.aim_fov_y` → forwarded to
          `TargetTracker.update_aim_fov` when both keys are present.

        Legacy sections (`hsv_engine.*`, `memory_esp.*`) are explicitly
        ignored here; `config.load_config` is responsible for emitting the
        user-facing diagnostic (see `EH1`/Req 7.7).

        Args:
            config: The new configuration dictionary. Replaces the coordinator's
                cached snapshot.
        """
        self.config = config

        # AI engine hot-reload.
        ai_config = config.get('ai_engine')
        if isinstance(ai_config, dict) and self.ai_engine is not None:
            try:
                self.ai_engine.update_config(ai_config)
                self._engine_errors['ai'] = 0
            except AIEngineException as e:
                self._engine_errors['ai'] = self._engine_errors.get('ai', 0) + 1
                logger.warning(
                    "AI engine update_config failed (count=%d): %s",
                    self._engine_errors['ai'], e,
                )
            except EngineException as e:
                self._engine_errors['ai'] = self._engine_errors.get('ai', 0) + 1
                logger.warning(
                    "AI engine update_config failed with generic EngineException "
                    "(count=%d): %s",
                    self._engine_errors['ai'], e,
                )

        # Target tracker: the legacy ``TargetTracker.update_aim_fov``
        # hot-reload hook is gone with the class itself
        # (aim-pipeline-simplification req 2.13, 4.4). The HSV fallback
        # now reads its parameters per-call from the cached ``vision``
        # config slice in ``main.DetectionFramework``, so there is
        # nothing to forward here. ``target_tracker`` is retained on
        # ``self`` only as an opaque slot for the surviving 3-arg
        # construction shape.


__all__ = ['EngineCoordinator']
