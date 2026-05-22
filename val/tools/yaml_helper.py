"""YAML key removal helpers.

This module provides small, pure helpers to remove nested keys from a
YAML-derived Python ``dict`` using dotted-path syntax (e.g.
``"input.ib.dll_path"``).

The helpers are used:

* In task 8.1 of the ``single-config-streamlining`` spec, to strip legacy
  sections from ``config.yaml`` while preserving all other keys byte-for-byte
  at the structural level.
* In the static verifier (task 17.1), as a reusable primitive for cleaning up
  ``input.ib.dll_path`` and similar legacy entries.

Both :func:`remove_key` and :func:`remove_keys` never mutate their input.
They return a :func:`copy.deepcopy` of the provided ``dict`` with the
requested key(s) removed, so that deep structural equality of every
untouched key is preserved.

If the dotted path does not exist in the dict — either because an
intermediate segment is missing or because an intermediate node is not a
``dict`` — the deep copy is returned unchanged (no error is raised).
"""

from __future__ import annotations

import copy
from typing import Iterable

__all__ = ["remove_key", "remove_keys"]


def remove_key(yaml_dict: dict, dotted_key: str) -> dict:
    """Return a deep copy of ``yaml_dict`` with ``dotted_key`` removed.

    Parameters
    ----------
    yaml_dict:
        The source dictionary. It is not mutated.
    dotted_key:
        Dot-separated path to the nested key to remove, e.g.
        ``"input.ib.dll_path"``. An empty string or a path whose segments do
        not resolve to an existing key in a nested ``dict`` are treated as a
        no-op.

    Returns
    -------
    dict
        A ``copy.deepcopy`` of ``yaml_dict`` with the target key removed when
        present, otherwise an unchanged deep copy.
    """
    result = copy.deepcopy(yaml_dict)

    if not dotted_key:
        return result

    parts = dotted_key.split(".")
    parent = result
    for segment in parts[:-1]:
        if not isinstance(parent, dict) or segment not in parent:
            return result
        parent = parent[segment]

    if isinstance(parent, dict):
        parent.pop(parts[-1], None)

    return result


def remove_keys(yaml_dict: dict, dotted_keys: Iterable[str]) -> dict:
    """Return a deep copy of ``yaml_dict`` with every path in ``dotted_keys`` removed.

    This is a convenience wrapper that applies :func:`remove_key` iteratively.
    The original ``yaml_dict`` is not mutated. Paths that do not exist are
    silently ignored, matching the single-key behaviour.
    """
    result = copy.deepcopy(yaml_dict)
    for dotted_key in dotted_keys:
        result = remove_key(result, dotted_key)
    return result
