#!/bin/bash
python -m pytest -s --tb=native --durations=5 --cov=chutes_miner_gpu --cov-report=term tests
python -m coverage report --fail-under=80