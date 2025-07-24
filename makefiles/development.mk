.PHONY: venv
venv: ##@development Set up virtual environment
venv:
	@echo "Setting up environment";
	${POETRY} install --no-root
	

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
				dockerfile="docker/$$pkg_name/Dockerfile"; \
				available_targets=$$(docker build --progress=plain -f $$dockerfile --target help . 2>/dev/null | grep "^FROM" | sed 's/.*AS \([^[:space:]]*\).*/\1/' || echo ""); \
				if [ -z "$$available_targets" ]; then \
					available_targets=$$(grep -i "^FROM.*AS" $$dockerfile | sed 's/.*AS[[:space:]]*\([^[:space:]]*\).*/\1/' | tr '[:upper:]' '[:lower:]' || echo "production development"); \
				fi; \
				for stage_target in $$available_targets; do \
					if [[ "$$stage_target" == production* ]]; then \
						if [[ "$$stage_target" == *-* ]]; then \
							gpu_suffix=$$(echo $$stage_target | sed 's/production-//'); \
							image_tag="$$pkg_version-$$gpu_suffix"; \
							image_name="$$pkg_name"; \
						else \
							image_tag="$$pkg_version"; \
							image_name="$$pkg_name"; \
						fi; \
						echo "Building production target: $$stage_target -> $$image_name:$$image_tag"; \
						DOCKER_BUILDKIT=1 docker build --progress=plain --target $$stage_target \
							-f $$dockerfile \
							-t $$image_name:${BRANCH_NAME}-${BUILD_NUMBER} \
							-t $$image_name:$$image_tag \
							--build-arg PROJECT_DIR=$$target \
							--build-arg PROJECT=$$pkg_name \
							${args} .; \
					elif [[ "$$stage_target" == development* ]]; then \
						if [[ "$$stage_target" == *-* ]]; then \
							gpu_suffix=$$(echo $$stage_target | sed 's/development-//'); \
							image_tag="$$pkg_version-$$gpu_suffix"; \
							image_name="$${pkg_name}_development"; \
						else \
							image_tag="$$pkg_version"; \
							image_name="$${pkg_name}_development"; \
						fi; \
						echo "Building development target: $$stage_target -> $$image_name:$$image_tag"; \
						DOCKER_BUILDKIT=1 docker build --progress=plain --target $$stage_target \
							-f $$dockerfile \
							-t $$image_name:${BRANCH_NAME}-${BUILD_NUMBER} \
							-t $$image_name:$$image_tag \
							--build-arg PROJECT_DIR=$$target \
							--build-arg PROJECT=$$pkg_name \
							--cache-from $$pkg_name:${BRANCH_NAME}-${BUILD_NUMBER} \
							${args} .; \
					fi; \
				done; \
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