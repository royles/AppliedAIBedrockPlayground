#!/usr/bin/env python3
"""
Cloudera AI application entry point.

Register this file as the Application script in Cloudera AI:
  Applications → New Application → Script: entry.py

Why a separate entry.py?
  CAI sometimes launches Python apps through Jupyter's ipykernel, which adds
  extra arguments (e.g. -f /path/to/kernel.json). Those arguments break normal
  argparse handling in start.py. entry.py strips them before delegating.

Flow:
  entry.py  →  start.main()  →  install deps  →  start FastAPI (+ Vite in dev)
"""

import sys


def main() -> int:
    """Strip Jupyter kernel args, then run the shared launcher in start.py."""
    from start import main as start_main

    return start_main()


if __name__ == "__main__":
    # Keep only the script name; drop ipykernel's -f kernel.json (and anything else).
    sys.argv = [sys.argv[0]]
    raise SystemExit(main())
