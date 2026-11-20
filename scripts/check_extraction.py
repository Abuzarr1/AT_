"""Run the real extractor on a file and print what came out. Usage: python scripts/check_extraction.py <file>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extractor import extract_items  # noqa: E402
from utils import read_input  # noqa: E402

path = Path(sys.argv[1])
res = extract_items(read_input(path.name, path.read_bytes()))
print(f"{len(res.items)} item(s)\n")
for i, it in enumerate(res.items, 1):
    print(f"{i}. brand={it.brand!r} part={it.part_number!r} qty={it.quantity} unit={it.unit!r}")
    print(f"   desc={it.description!r}\n   specs={it.specs!r}")
print("\nmeta:", res.meta)
print("notes:", res.notes)
