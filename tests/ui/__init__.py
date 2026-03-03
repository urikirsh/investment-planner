"""Shared package marker for UI tests.

Keeping UI tests under a package gives pytest stable import paths and avoids
module-name collisions when files with the same name exist in other test
directories.
"""
