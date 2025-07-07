.PHONY: venv
venv: ##@development Set up virtual environment
venv:
	@echo "Creating environment for: $(TARGET_NAMES)"; \
	# Set up root venv to avoid managing multiple venvs for now; \
	python -m venv .venv; \
	. .venv/bin/activate; \
	for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		echo "Setting up venv for for $$pkg_name"; \
		${POETRY} install -P $$target; \
	done
	

.PHONY: build
build: ##@development Build the docker images for all packages or specific TARGET_PROJECT
build: args ?= --network=host --build-arg BUILDKIT_INLINE_CACHE=1
build:
	@echo "Building images for: $(TARGET_NAMES)"
	@for target in $(TARGETS); do \
		pkg_name=$$(basename $$target); \
		pkg_version=$$(if [ -f "$$target/VERSION" ]; then head $$target/VERSION; else echo "dev"; fi); \
		if [ -d "docker/$$pkg_name" ]; then \
			if [ -f "docker/$$pkg_name/Dockerfile" ]; then \
				echo "Building images for $$pkg_name (version: $$pkg_version)"; \
				DOCKER_BUILDKIT=1 docker build --progress=plain --target production \
					-f docker/$$pkg_name/Dockerfile \
					-t $$pkg_name:${BRANCH_NAME}-${BUILD_NUMBER} \
					-t $$pkg_name:$$pkg_version \
					--build-arg PROJECT_DIR=$$target \
					--build-arg PROJECT=$$pkg_name \
					${args} .; \
				DOCKER_BUILDKIT=1 docker build --progress=plain --target development \
					-f docker/$$pkg_name/Dockerfile \
					-t $$pkg_name\_development:${BRANCH_NAME}-${BUILD_NUMBER} \
					-t $$pkg_name\_development:$$pkg_version \
					--build-arg PROJECT_DIR=$$target \
					--build-arg PROJECT=$$pkg_name \
					--cache-from $$pkg_name:${BRANCH_NAME}-${BUILD_NUMBER} \
					${args} .; \
			else \
				echo "Skipping $$pkg_name: docker/$$pkg_name/Dockerfile not found"; \
			fi; \
		else \
			echo "Skipping $$pkg_name: docker/$$pkg_name directory not found"; \
		fi; \
	done

.PHONY: infrastructure
infrastructure: ##@development Set up infrastructure for tests
infrastructure:
	@echo "Skipping make infra..."

.PHONY: clean
clean: ##@development Clean up any dependencies
clean:
	@echo "Skipping clean..."

.PHONY: ci
ci: ##@development Run CI pipeline
ci: clean build infrastructure lint test clean