.PHONY: lint-local
lint-local: ##@local Run all lint tools locally on all packages or specific TARGET_PROJECT
lint-local:
	@echo "Running lint for: $(TARGET_NAMES)"
	@for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		echo "Running lint for $$pkg_name ($$target)"; \
		ruff check; \
		ruff format --check --line-length 100; \
	done

.PHONY: clean-imports
clean-imports: ##@local Remove unused imports from all packages or specific TARGET_PROJECT
clean-imports:
	@echo "Cleaning imports for: $(TARGET_NAMES)"
	@for target in $(TARGETS); do \
		echo "Cleaning imports for $$target"; \
		autoflake --in-place --remove-all-unused-imports --recursive $$target tests; \
	done

.PHONY: reformat
reformat: ##@local Reformat all packages or specific TARGET_PROJECT
reformat: clean-imports
	@echo "Reformatting: $(TARGET_NAMES)"
	@for target in $(TARGETS); do \
		echo "Reformatting $$pkg_name ($$target)"; \
		ruff format --check --line-length 100; \
	done

.PHONY: test-local
test-local: ##@local Run test suite locally on all packages or specific TARGET_PROJECT
test-local:
	@echo "Running tests locally for: $(TARGET_NAMES)"
	@for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		if [ -d "docker/$$pkg_name" ]; then \
			echo "Running tests for $$pkg_name ($$target)"; \
			cd $$target; \
			${POETRY} run pytest -s --tb=native --durations=5 --cov=. --cov-report=html ../../tests/$$pkg_name; \
			${POETRY} run coverage report --fail-under=90; \
		else \
			echo "Skipping $$pkg_name: tests/$$pkg_name directory not found"; \
		fi; \
	done