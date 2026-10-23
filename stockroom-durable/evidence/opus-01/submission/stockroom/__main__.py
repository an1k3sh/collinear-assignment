"""Entry point: ``python -m stockroom PROGRAM --inventory IN --out OUT``."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
