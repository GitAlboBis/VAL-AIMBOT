"""
Execution-Provider selector — pure function for picking an inference backend.

Extracted from `AIVisionEngine.load_model` so the cascade rules are unit-testable in
isolation (Req 9.4 idempotence; Properties 4–7).

Contract:

    select_provider(
        host_arch:           str,                      # "arm64" | "x86_64" | "other"
        available_providers: Sequence[str],            # e.g. ort.get_available_providers()
        config_override:     str,                      # "auto" | "qnn" | "directml" | "cpu"
        candidate_factories: Mapping[str, ProviderFactory],
    ) -> Tuple[Provider, str]

Pure: no module-level state, no clock reads, no environment reads. The function depends
only on its arguments and on the side effects of calling each factory's `.load()` method
(Reqs 3.10, 9.4).

Cascade rules (mirrors design.md decision table):

    config_override == "qnn"      -> ["qnn"]
    config_override == "directml" -> ["directml"]
    config_override == "cpu"      -> ["cpu"]
    config_override == "auto" AND host_arch == "arm64"
                                  AND "QNNExecutionProvider" in available_providers
                                  -> ["qnn", "directml", "cpu"]
    otherwise                     -> ["directml", "cpu"]

Unknown override values normalize to "auto" and emit a WARN (Req 4.6).

The cascade is evaluated in order; the first factory whose `.load()` returns `True` wins.
On `False` or any caught exception, the candidate is recorded with a reason and the loop
continues (Req 3.4). When every candidate fails, `AIEngineException` is raised with a
message enumerating each `(name, reason)` (Reqs 3.5, 4.7).

When fallback occurs (at least one entry in `failures` before a success), exactly one
INFO log is emitted in the form
``EP fallback: {first_failed} -> {chosen} (reason: {first_reason})`` (Req 6.5).
"""

from __future__ import annotations

import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Mapping,
    Sequence,
    Tuple,
)

from exceptions import AIEngineException

logger = logging.getLogger(__name__)


if TYPE_CHECKING:  # pragma: no cover — typing only
    # A "Provider" is any object exposing `.load() -> bool` and `.release() -> None`.
    # We model it as `Any` at runtime to avoid a hard import dependency on a concrete
    # provider class (the real types live in `engines.qnn_provider`,
    # `engines.directml_provider`, etc.).
    Provider = Any
else:
    Provider = Any


# ``ProviderFactory`` is a zero-argument callable that constructs and returns a fresh
# Provider instance. The selector invokes the factory at most once per cascade entry and
# only when that entry is reached (Req 3.6 short-circuit).
ProviderFactory = Callable[[], Provider]


_ALLOWED_OVERRIDES = ("auto", "qnn", "directml", "cpu")


def _normalize_override(config_override: Any) -> str:
    """Normalize ``config_override`` to one of the allowed values.

    Per Req 4.6: unknown string values warn and fall back to ``"auto"``.
    Non-string values (defensive guard for callers that bypassed the config validator)
    also fall back to ``"auto"`` with a WARN.
    """
    if isinstance(config_override, str):
        normalized = config_override.strip().lower()
        if normalized in _ALLOWED_OVERRIDES:
            return normalized
    logger.warning(
        "ai_engine.execution_provider=%r unrecognized; falling back to auto",
        config_override,
    )
    return "auto"


def _build_cascade(
    host_arch: str,
    available_providers: Sequence[str],
    override: str,
) -> List[str]:
    """Compute the ordered cascade of backend names to try.

    Implements the decision table in design.md verbatim (Reqs 3.1, 3.2, 3.6, 4.3, 4.4,
    4.5).
    """
    if override == "qnn":
        return ["qnn"]
    if override == "directml":
        return ["directml"]
    if override == "cpu":
        return ["cpu"]
    # override == "auto"
    if host_arch == "arm64" and "QNNExecutionProvider" in available_providers:
        return ["qnn", "directml", "cpu"]
    return ["directml", "cpu"]


def select_provider(
    host_arch: str,
    available_providers: Sequence[str],
    config_override: str,
    candidate_factories: Mapping[str, ProviderFactory],
) -> Tuple[Provider, str]:
    """Select and load an inference provider.

    Args:
        host_arch: Normalized host architecture string. Expected values are
            ``"arm64"``, ``"x86_64"``, or ``"other"``; any other value is treated as
            non-arm64 and routes to the DirectML/CPU cascade.
        available_providers: Sequence of execution-provider identifiers reported by
            ``onnxruntime.get_available_providers()``. May be empty if ONNX Runtime is
            not importable on the host.
        config_override: User-supplied override from
            ``ai_engine.execution_provider``. Allowed values are ``"auto"``, ``"qnn"``,
            ``"directml"``, ``"cpu"``; unknown values warn and fall back to ``"auto"``
            (Req 4.6). Pinned values (``"qnn"``, ``"directml"``, ``"cpu"``) yield a
            cascade of length 1 (Reqs 4.3, 4.4, 4.5).
        candidate_factories: Mapping of cascade keys (``"qnn"``, ``"directml"``,
            ``"cpu"``) to zero-argument factories returning Provider instances. Only
            keys appearing in the resolved cascade are looked up; factories for keys
            not in the cascade are never invoked (Req 3.6 short-circuit).

    Returns:
        A tuple ``(loaded_provider, backend_name)`` where ``backend_name`` is the
        cascade key whose factory's ``.load()`` returned ``True``.

    Raises:
        AIEngineException: Every candidate in the resolved cascade failed to load
            (Reqs 3.5, 4.7). The exception message enumerates each
            ``{name}: {reason}`` pair in cascade order.
    """
    override = _normalize_override(config_override)
    cascade = _build_cascade(host_arch, available_providers, override)

    failures: List[Tuple[str, str]] = []

    for backend_name in cascade:
        factory = candidate_factories.get(backend_name)
        if factory is None:
            # Defensive: a cascade entry without a registered factory is treated as a
            # synthetic load failure rather than a programming error, so the cascade
            # can still fall through to a viable candidate.
            failures.append((backend_name, "no factory registered"))
            continue

        try:
            provider = factory()
            if provider.load():
                if failures:
                    first_failed, first_reason = failures[0]
                    # Single INFO record per Req 6.5. Format is asserted by
                    # `test_arm64_qnn_load_false_falls_back_to_directml_with_single_info_log`.
                    logger.info(
                        "EP fallback: %s -> %s (reason: %s)",
                        first_failed,
                        backend_name,
                        first_reason,
                    )
                return provider, backend_name
            failures.append((backend_name, "load() returned False"))
        except Exception as e:  # noqa: BLE001 — broad-by-design per Req 3.4
            logger.warning("EP candidate %s failed: %s", backend_name, e)
            failures.append((backend_name, str(e)))

    # Cascade exhausted with no successful load (Reqs 3.5, 4.7).
    raise AIEngineException(
        "all execution providers failed: "
        + "; ".join(f"{name}: {reason}" for name, reason in failures)
    )


__all__ = ["ProviderFactory", "select_provider"]
