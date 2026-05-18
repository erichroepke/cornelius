#!/bin/bash
# Wrapper script for re-indexing the Brain
# Usage: ./run_index.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BRAIN_PATH="${BRAIN_PATH:-/Users/erichroepke/Desktop/ZEUS-BRAIN-STARTUP-2026-05-17/Brain/wiki}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-1}"
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/index_brain.py" "$@"
