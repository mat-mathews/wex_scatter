#!/usr/bin/env python3
"""Scatter - .NET dependency analyzer.

Thin entry point so `python scatter.py` works alongside `python -m scatter`
and the installed `scatter` console script.  The real implementation lives
in scatter/__main__.py.  Do not delete this file — it's the simplest
invocation path for users who haven't pip-installed the package.
"""
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("scatter", run_name="__main__", alter_sys=True)
