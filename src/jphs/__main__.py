"""``python -m jphs {jphide|jpseek} ...`` entry point."""

from __future__ import annotations

import sys

from .cli import jphide, jpseek


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] not in ("jphide", "jpseek"):
        sys.stderr.write("Usage: python -m jphs {jphide|jpseek} ...\n")
        return 1
    if argv[0] == "jphide":
        return jphide(argv[1:])
    return jpseek(argv[1:])


raise SystemExit(main())
