.PHONY: lint-local
lint-local: ##@local Run all lint tools locally on all packages or specific TARGET_PROJECT
lint-local:
	@echo "Running lint for: $(TARGET_NAMES)"; \
	root_dir=$$(pwd); \
	exit_code=0; \
	for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		echo "--------------------------------------------------------"; \
		echo "Running lint for $$pkg_name ($$target)"; \
		echo "--------------------------------------------------------"; \
		cd $$target; \
		ruff check || exit_code=1; \
		ruff format --check --line-length 100 || exit_code=1; \
		cd $$root_dir; \
	done; \
	exit $$exit_code

.PHONY: reformat
reformat: ##@local Reformat all packages or specific TARGET_PROJECT
reformat:
	@echo "Reformatting: $(TARGET_NAMES)"; \
	root_dir=$$(pwd); \
	for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		echo "--------------------------------------------------------"; \
		echo "Running reformat for $$pkg_name ($$target)"; \
		echo "--------------------------------------------------------"; \
		echo "Reformatting $$pkg_name ($$target)"; \
		cd $$target; \
		ruff format --line-length 100; \
		cd $$root_dir; \
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