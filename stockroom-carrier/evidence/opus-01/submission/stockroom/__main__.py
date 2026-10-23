"""Entry point: python -m stockroom PROGRAM --inventory INPUT --out OUTPUT ..."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
