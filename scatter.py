#!/usr/bin/env python3
"""Scatter - .NET dependency analyzer. CLI entry point for backward compatibility.

Usage: python scatter.py [args...]
Or:    python -m scatter [args...]
"""
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("scatter", run_name="__main__", alter_sys=True)
