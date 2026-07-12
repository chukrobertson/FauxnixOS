from __future__ import annotations

from membrie.db import init_membrie_db
from membrie.ui.tray import run_tray


def main():
    init_membrie_db()
    run_tray()


if __name__ == "__main__":
    main()
