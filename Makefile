.PHONY: help run test smoke eval clean tunnel

VENV = .venv/bin

help:
	@echo "Available commands:"
	@echo "  make run    - Start the Streamlit Procurement UI"
	@echo "  make tunnel - Expose the running app to a secure public HTTPS URL (Cloudflare)"
	@echo "  make test   - Run all 134 offline unit tests"
	@echo "  make smoke  - Run page smoke tests (app, parser, compare)"
	@echo "  make eval   - Run Groq evaluation benchmark on test cases"
	@echo "  make clean  - Clean temporary Python caches"

run:
	$(VENV)/streamlit run app.py

tunnel:
	$(VENV)/cloudflared tunnel --url http://localhost:8501

test:
	$(VENV)/pytest --tb=short -q

smoke:
	$(VENV)/python evaluation/smoke.py

eval:
	$(VENV)/python -m evaluation.runner --extractor extractor:extract_items --limit 2

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
