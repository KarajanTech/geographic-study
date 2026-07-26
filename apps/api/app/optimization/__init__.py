"""Optimization engine.

Deliberately independent of the HTTP API and the database: every function here
takes plain arrays and returns plain dataclasses, so it can be tested, reused
by a worker, or swapped for a different solver (CP-SAT, in Phase 8) without
touching this module's callers.
"""
