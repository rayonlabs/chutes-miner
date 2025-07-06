.PHONY: tag
tag: ##@images Tag docker images from the build step for Parachutes repo
tag:
tag:
	@images=$$(find docker -maxdepth 1 -type d ! -path docker | sort); \
	image_names=$$(echo $$images | xargs -n1 basename | tr '\n' ' '); \
	echo "Tagging images for: $$image_names"; \
	for image_dir in $$images; do \
		pkg_name=$$(basename $$image_dir); \
		pkg_version=$$(if [ -f "$$pkg_name/VERSION" ]; then head "$$pkg_name/VERSION" | grep -Eo "\d+.\d+.\d+"; else echo "0.0.0"; fi); \
		if [ -f "docker/$$pkg_name/image.conf" ]; then \
			echo "Tagging $$pkg_name (version: $$pkg_version)"; \
			registry=$$(cat docker/$$pkg_name/image.conf); \
			docker tag $$pkg_name:$$pkg_version $$registry:k3s; \
		else \
			echo "Skipping $$pkg_name: docker/$$pkg_name/image.conf not found"; \
		fi; \
	done

.PHONY: images
images: ##@images Build all docker images
images: args ?= --network=host --build-arg BUILDKIT_INLINE_CACHE=1
images:
	@images=$$(find docker -maxdepth 1 -type d ! -path docker | sort); \
	filtered_images=""; \
	for image_dir in $$images; do \
		pkg_name=$$(basename $$image_dir); \
		if ! echo "$(TARGET_NAMES)" | grep -q "$$pkg_name"; then \
			filtered_images="$$filtered_images $$image_dir"; \
		fi; \
	done; \
	image_names=$$(echo $$filtered_images | xargs -n1 basename | tr '\n' ' '); \
	echo "Building images for: $$image_names"; \
	for image_dir in $$filtered_images; do \
		pkg_name=$$(basename $$image_dir); \
		pkg_version=$$(if [ -f "$$pkg_name/VERSION" ]; then head "$$pkg_name/VERSION" | grep -Eo "\d+.\d+.\d+"; else echo "0.0.0"; fi); \
		if [ -f "$$image_dir/Dockerfile" ]; then \
			echo "Building images for $$pkg_name (version: $$pkg_version)"; \
			DOCKER_BUILDKIT=1 docker build --progress=plain --target production \
				-f $$image_dir/Dockerfile \
				-t $$pkg_name:${BRANCH_NAME}-${BUILD_NUMBER} \
				-t $$pkg_name:$$pkg_version \
				--build-arg PROJECT_DIR=$$pkg_name \
				--build-arg PROJECT=$$pkg_name \
				${args} .; \
			DOCKER_BUILDKIT=1 docker build --progress=plain --target development \
				-f $$image_dir/Dockerfile \
				-t $$pkg_name\_development:${BRANCH_NAME}-${BUILD_NUMBER} \
				-t $$pkg_name\_development:$$pkg_version \
				--build-arg PROJECT_DIR=$$pkg_name \
				--build-arg PROJECT=$$pkg_name \
				--cache-from $$pkg_name:${BRANCH_NAME}-${BUILD_NUMBER} \
				${args} .; \
		else \
			echo "Skipping $$pkg_name: $$image_dir/Dockerfile not found"; \
		fi; \
	done