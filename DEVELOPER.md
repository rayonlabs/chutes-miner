# Developer Guide

This document provides guidance for new developers on setting up and working with the Chutes monorepo.

## Repository Structure

This is a monorepo containing multiple all the packages for mining on Chutes.

```
src/
├── chutes-common/
├── chutes-miner/
├── chutes-miner-cli/
├── chutes-miner-gpu/
├── chutes-registry/
└── graval-bootstrap/
```

Each package has its own Docker configuration in the `docker/` directory and corresponding tests in the `tests/` directory.

## Prerequisites

- Python 3.12+
- Poetry for dependency management
- Docker and Docker Compose
- Make

## Initial Setup

### 1. Clone and Environment Setup

```bash
git clone <repository-url>
cd chutes-miner
```

### 2. Virtual Environment

Set up a Python virtual environment for all packages:

```bash
make venv
```

This will create a shared `.venv` directory and install dependencies for all packages using Poetry.

**__Currently a single venv is used for all packages.  This could be problematic if packages have conflicting dependencies.  For now manage dependencies wisely, later these can be split out.__** 

### 3. Activate Virtual Environment

```bash
source .venv/bin/activate
```

## Working with the Monorepo

### Available Commands

The Makefile provides comprehensive tooling for development. To see all available commands:

```bash
make help
```

### Package Management

List all packages in the monorepo:

```bash
make list-packages
```

Most commands can target specific packages or run across all packages:

```bash
# Run on all packages
make build

# Run on specific package
make build chutes-miner
```

### Managing Docker Images

#### Building Docker Images 

Build development and production Docker images:

```bash
# Build images for all packages
make build

# Build specific package
make build chutes-miner
```

Some images such as `cache-cleaner` do not contain source code. Standalone images are managed with a separate command.
```bash
# Build images for all packages
make images
```

#### Tagging Docker Images

Images are build locally using package names.  To tag images for docker hub:
```bash
make tag
```

This will tag images according to the registry in their respective `docker/<component>/image.conf` file and use the version from the package.

## Development Workflow

### 1. Code Changes

Make your changes in the appropriate package under `src/`.

### 2. Local Testing

Run tests locally without Docker:

```bash
# Test all packages
make test-local

# Test specific package
make test-local chutes-miner
```

### 3. Linting and Formatting

Run linting locally:

```bash
# Lint all packages
make lint-local

# Lint specific package
make lint-local chutes-miner
```

Format your code if necessary:

```bash
# Format all packages
make reformat

# Format specific package
make reformat chutes-miner
```

### 4. Docker-based Testing

For a complete test environment that matches CI:

```bash
# Run tests in Docker
make test
```

## Package-Specific Development

### chutes-miner

The main mining package includes a full development environment with PostgreSQL and Redis:

```bash
# Start the development environment
cd docker/chutes-miner
docker compose up -d postgres redis

# Run the API server
docker compose up api

# Seed the database with test data
docker compose run --rm db-seed
```

The API will be available at `http://localhost:8080`.

### Other Packages

Most other packages (chutes-cacheclean, chutes-registry, graval-bootstrap) follow a simpler pattern with shell, test, and lint services available.

## Testing

### Test Structure

Tests are organized by package:

```
tests/
├── chutes-cacheclean/
├── chutes-miner/
├── chutes-miner-gpu/
├── chutes-registry/
└── graval-bootstrap/
```

### Running Tests

**Local Testing (faster for development):**
```bash
make test-local <package-name>
```

**Docker Testing (matches CI environment):**
```bash
make test <package-name>
```

### Test Coverage

Tests include coverage reporting. Local tests generate HTML coverage reports and enforce a 90% coverage threshold.  Packages that do not enforce 90% code coverage will get there.  If you change code, add tests for it.

## CI Pipeline

The full CI pipeline can be run locally:

```bash
make ci
```

This runs: clean → build → infrastructure → lint → test → clean

## Docker Configuration

### Package-specific Docker Files

Each package may have its own Dockerfile in `docker/<package-name>/Dockerfile`.

### Docker Compose Structure

- `docker-compose.base.yaml`: Base configuration with common settings
- `docker-compose.yaml`: Package-specific services and overrides
- `local.env`: Environment variables for local development
- `image.conf`: Docker registry configuration for tagging

### Common Services

Most packages include these Docker Compose services:

- `shell`: Interactive bash shell for debugging
- `test`: Runs the test suite
- `lint`: Runs linting tools

## Environment Variables

Key environment variables for development:

- `PROJECT`: Project name (default: chutes-miner)
- `BRANCH_NAME`: Git branch name (default: local)
- `BUILD_NUMBER`: Build number (default: 0)
- `TARGET_PROJECT`: Specific package to target for commands

## Troubleshooting

### Common Issues

1. **Poetry installation fails**: Ensure you have Poetry >2.1 and Python 3.12+
2. **Docker build fails**: Check that you have sufficient disk space and Docker is running
3. **Port conflicts**: The chutes-miner package uses ports 5432 (PostgreSQL), 6379 (Redis), and 8080 (API)

### Getting Help

- Run `make help` to see all available commands
- Check the `scripts/` directory for the actual implementation of test and lint scripts
- Look at the Docker Compose files for each package to understand the available services

## Contributing

1. Create a feature branch
2. Make your changes
3. Run local tests and linting
4. Build Docker images to ensure they work
5. Run the full CI pipeline locally
6. Create a pull request

For more detailed command information, always refer to `make help` which provides up-to-date documentation of all available targets.