"""Developer tooling. Deliberately outside the installed package.

`pyproject.toml`'s `packages.find` includes only `strikefactor*` and
`analysis*`, so nothing here ships with the game. It is importable from the
repository root, which `[tool.pytest.ini_options] pythonpath` guarantees for
the test suite and the working directory guarantees for `python -m tools.*`.
"""
