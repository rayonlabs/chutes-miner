.PHONY: lint
lint: ##@lint Run all lint tools on all packages or specific TARGET
lint:
	@echo "Running lint for: $(TARGET_NAMES)"
	@for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		if [ -d "docker/$$pkg_name" ]; then \
			echo "Running lint for $$pkg_name ($$target)"; \
			PROJECT=$$pkg_name ${DC} -p $$pkg_name -f docker/$$pkg_name/${COMPOSE_FILE} run --rm --no-deps lint; \
		else \
			echo "Skipping $$pkg_name: docker/$$pkg_name directory not found"; \
		fi; \
	done