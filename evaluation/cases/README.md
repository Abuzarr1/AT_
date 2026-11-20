# Benchmark cases

One `.json` file per real RFQ. Copy `_template.json`, fill it from the source document
(not from the tool's output), and save it here. Files starting with `_` are ignored.

Rules:
- `expected_items` is the truth from the source document. Do not copy it from the tool.
- Leave `part_number` empty when the source has none. Never guess.
- `manual_minutes` and `review_minutes` are optional. Only measured values go in.
- These files can hold end-client names. They are git-ignored. Never commit them.
