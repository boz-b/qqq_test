PYTHON := venv/bin/python
PIP := venv/bin/pip

.PHONY: setup compile test smoke db-dry-run shell-check pip-check git-check ci pre-pr agent-status agent-checks

setup:
	./scripts/setup_local_runtime.sh

venv/bin/python:
	./scripts/setup_local_runtime.sh

compile: venv/bin/python
	$(PYTHON) -m py_compile *.py scripts/*.py

test: venv/bin/python
	$(PYTHON) scripts/test_news_summary_fallback.py
	$(PYTHON) scripts/test_calendar_actual_enrichment.py
	$(PYTHON) scripts/test_static_public_data.py
	$(PYTHON) scripts/test_no_tracked_secrets.py

smoke: venv/bin/python
	$(PYTHON) dashboard.py --smoke-test

db-dry-run: venv/bin/python
	$(PYTHON) scripts/db_migrate.py --dry-run

shell-check:
	bash -n scripts/*.sh

pip-check: venv/bin/python
	$(PIP) check

ci: compile test shell-check db-dry-run smoke pip-check

git-check:
	git diff --check
	git diff --cached --check

pre-pr: ci git-check

agent-status:
	./scripts/agent_task.sh status

agent-checks:
	./scripts/agent_task.sh checks
