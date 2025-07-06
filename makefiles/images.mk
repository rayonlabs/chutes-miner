.PHONY: tag
tag: ##@images Tag docker images from the build step for Parachutes repo
tag:
tag:
	@echo "Tagging images for: $(TARGET_NAMES)"
	@for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		pkg_version=$$(if [ -f "$$target/VERSION" ]; then head "$$target/VERSION" | grep -Eo "\d+.\d+.\d+"; else echo "0.0.0"; fi); \
		if [ -d "docker/$$pkg_name" ]; then \
			if [ -f "docker/$$pkg_name/image.conf" ]; then \
				echo "Tagging images for $$pkg_name (version: $$pkg_version)"; \
				registry=$$(cat docker/$$pkg_name/image.conf); \
				docker tag $$pkg_name:$$pkg_version $$registry:$$pkg_version; \
			else \
				echo "Skipping $$pkg_name: docker/$$pkg_name/image.conf not found"; \
			fi; \
		else \
			echo "Skipping $$pkg_name: docker/$$pkg_name directory not found"; \
		fi; \
	done