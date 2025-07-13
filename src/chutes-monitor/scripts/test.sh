#!/bin/bash
python -m pytest -s --tb=native --durations=5 --cov=chutes_monitor --cov-report=term tests
python -m coverage report --fail-under=90