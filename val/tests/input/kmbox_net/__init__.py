"""Tests for the ``input.kmbox_net_driver`` rewrite (spec ``kmbox-net-arm64-udp``).

This package houses unit and property-based tests that exercise the pure-Python
UDP rewrite of ``KmBoxNetDriver``. All I/O is performed through the in-memory
fakes defined in ``conftest.py``; no real sockets are opened during testing.
"""
