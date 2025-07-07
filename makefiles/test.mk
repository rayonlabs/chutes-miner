.PHONY: test
test: ##@test Run test suite on all packages or specific TARGET_PROJECT
test: service ?= test
test:
	@echo "Running tests for: $(TARGET_NAMES)"
	@for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		if [ -d "docker/$$pkg_name" ]; then \
			if PROJECT=$$pkg_name ${DC} -p $$pkg_name -f docker/$$pkg_name/docker-compose.yaml -f docker/$$pkg_name/docker-compose.base.yaml config --services | grep -q "^$(service)$$"; then \
				echo "Running $(service) for $$pkg_name ($$target)"; \
				PROJECT=$$pkg_name ${DC} -p $$pkg_name -f docker/$$pkg_name/docker-compose.yaml -f docker/$$pkg_name/docker-compose.base.yaml run --rm --no-deps $(service); \
			else \
				echo "Skipping $$pkg_name: '$(service)' service not found in docker-compose configuration"; \
			fi; \
		else \
			echo "Skipping $$pkg_name: docker/$$pkg_name directory not found"; \
		fi; \
	done