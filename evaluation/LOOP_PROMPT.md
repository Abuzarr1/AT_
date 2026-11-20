# Loop prompt: check the app for errors and problems

Paste everything below the line into your coding agent (Antigravity agent or Claude Code),
with the project folder open and the venv active.

---

You are the QA loop for the Procurement Assistant (Python, Streamlit, LangGraph, Abdullah Traders).
Read the "Hard rules" in the handoff document first and keep all of them.

Run up to 5 iterations. Each iteration does these steps in order:

1. CHECK (offline only, never call Groq in this loop):
   a. `pytest`  (expect all tests to pass, currently 47 + 11 benchmark tests)
   b. `python -m evaluation.smoke`  (each Streamlit page must load with no exception)
   c. Read `outputs/eval_report.md` if it exists. It comes from the last manual benchmark run.
2. LIST every problem found: failing test, page exception, and each line under "Per-case errors"
   (MISSED, EXTRA, INVENTED, wrong brand, part number or quantity).
3. PICK ONE problem, the one that risks a wrong part number or a leaked end-client name first.
4. FIX it with the smallest change to prompts, `promote_model`, validation, or code.
   Add or update a test that fails before the fix and passes after it.
5. RE-RUN step 1. If something that passed before now fails, revert the change.

Rules for the loop:
- Never send email, never print or log the API key, never touch `.env`, `data/suppliers.csv`,
  `data/banned_terms.txt`, `data/company.json` or `evaluation/cases/*.json`.
- Never invent data. Missing prices, part numbers or quantities stay empty and get flagged.
- Do not call the LLM and do not add retry loops. Real-LLM benchmark runs are done by Abuzar only:
  `python -m evaluation.runner --extractor module:function`
- Stop early when all checks are clean, when you make no progress for 2 iterations,
  or when a fix needs a decision from Abuzar.

Final report, short: iterations used, problems fixed (one line each), problems still open,
the new test count, and the exact files changed. Then ask Abuzar to re-run the manual
benchmark and send the new `outputs/eval_report.md`.
