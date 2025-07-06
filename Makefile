SHELL := /bin/bash -e -o pipefail
PROJECT ?= chutes-miner
BRANCH_NAME ?= local
BUILD_NUMBER ?= 0
IMAGE ?= ${PROJECT}:${BRANCH_NAME}-${BUILD_NUMBER}
COMPOSE_FILE=docker-compose.yaml
COMPOSE_BASE_FILE=docker-compose.base.yaml
DC=docker compose
SERVICE := chutes-miner
POETRY ?= "poetry"
# VERSION := $(shell head VERSION | grep -Eo "\d+.\d+.\d+")

# Monorepo configuration
SRC_DIR := src
PACKAGES := $(shell find ${SRC_DIR} -maxdepth 1 -type d ! -path ${SRC_DIR} | sort)
PACKAGE_NAMES := $(notdir $(PACKAGES))

# Target specific project or all projects
ifeq ($(words $(MAKECMDGOALS)),2)
	TARGET := $(word 2,$(MAKECMDGOALS))
endif

ifdef TARGET
	ifneq ($(wildcard ${SRC_DIR}/${TARGET}),)
		TARGETS := ${SRC_DIR}/${TARGET}
		TARGET_NAMES := ${TARGET}
	else
		$(error Project ${TARGET} not found in ${SRC_DIR})
	endif
else
	TARGETS := $(PACKAGES)
	TARGET_NAMES := $(PACKAGE_NAMES)
endif

# Create dynamic package-specific targets, filtering out packages from goals
$(foreach pkg,$(PACKAGE_NAMES),$(eval $(pkg): ; @$(MAKE) --no-print-directory TARGET_PROJECT=$(pkg) $(filter-out $(pkg),$(MAKECMDGOALS))))

# Prevent Make from trying to build package names as files
.PHONY: $(PACKAGE_NAMES)

.DEFAULT_GOAL := help

.EXPORT_ALL_VARIABLES:

include makefiles/development.mk
include makefiles/help.mk
include makefiles/lint.mk
include makefiles/local.mk
include makefiles/test.mk
include makefiles/images.mk

.PHONY: list-packages
list-packages: ##@other List all packages in the monorepo
	@echo "Available packages:"
	@for pkg in $(PACKAGE_NAMES); do echo "  - $$pkg"; done
	@echo ""
	@echo "Usage: make <target> TARGET_PROJECT=<package_name>"