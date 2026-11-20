"""Offline app smoke test: loads each Streamlit page and reports exceptions.

Usage: python -m evaluation.smoke
Makes no LLM call because it only renders the pages, it does not click buttons.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["app.py", "pages/2_Quote_Parser.py", "pages/3_Compare_Quotes.py"]


def main() -> int:
    from streamlit.testing.v1 import AppTest

    failed = 0
    for page in PAGES:
        target = ROOT / page
        if not target.exists():
            print(f"SKIP {page}: not found")
            continue
        at = AppTest.from_file(str(target), default_timeout=30).run()
        if at.exception:
            failed += 1
            print(f"FAIL {page}")
            for exc in at.exception:
                print("  ", str(exc.value)[:300])
        else:
            print(f"OK   {page}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
