#!/usr/bin/env bash
#
# run_alignment.sh
#
# Reproducible alignment pipeline for the Assignment:
#  - Creates/updates a conda environment from environment.yml (if needed)
#  - Prepares corpus directory (copies wav + transcript files)
#  - Downloads MFA models (dictionary, acoustic, g2p)
#  - Runs initial alignment
#  - Generates OOV dictionary with G2P
#  - Runs final alignment using the generated OOV dictionary
#  - Prints a small before/after "spn" (unknown/noise phone) report
#
# Usage:
#   bash scripts/run_alignment.sh
#   bash scripts/run_alignment.sh --help
#
# Notes:
#  - This script assumes you have 'conda' available on PATH (Miniconda / Anaconda).
#  - If 'mfa' is not yet on PATH, the script will attempt to create/update the 'mfa'
#    environment from environment.yml and will use `conda run -n mfa mfa` to invoke MFA.
#  - Run this from anywhere; the script uses its location to find repository root.
#

set -euo pipefail
IFS=$'\n\t'

print_usage() {
  cat <<'USAGE'
Usage: run_alignment.sh [--help]

Options:
  --help      Show this help and exit

What this script does:
  1) (If necessary) create/update conda env from environment.yml (name: mfa)
  2) prepare corpus directory (copy audio + transcripts into ./my_corpus)
  3) download models used by MFA (dictionary, acoustic, g2p)
  4) run initial alignment -> ./my_alignment_results
  5) generate OOV dictionary -> ./my_oov_dictionary.dict
  6) run final alignment using the OOV dictionary -> ./my_final_results
  7) show a small before/after summary (counts of 'spn' tokens)
USAGE
}

# simple arg parsing
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  print_usage
  exit 0
fi

# Resolve paths relative to the script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Configurable variables
CORPUS_DIR="$REPO_ROOT/my_corpus"
INITIAL_OUTPUT_DIR="$REPO_ROOT/my_alignment_results"
FINAL_OUTPUT_DIR="$REPO_ROOT/my_final_results"
OOV_DICT="$REPO_ROOT/my_oov_dictionary.dict"

# MFA / model names (change here if you want to use another model)
DICTIONARY_MODEL="english_us_arpa"
ACOUSTIC_MODEL="english_us_arpa"
G2P_MODEL="english_us_arpa"

echo "Repository root: $REPO_ROOT"
echo "Corpus directory: $CORPUS_DIR"
echo "Initial alignment output: $INITIAL_OUTPUT_DIR"
echo "Final alignment output: $FINAL_OUTPUT_DIR"
echo ""

# Ensure 'conda' exists
if ! command -v conda >/dev/null 2>&1; then
  echo "ERROR: 'conda' not found in PATH. Please install Miniconda/Anaconda and re-run."
  exit 1
fi

# If 'mfa' is not on PATH, attempt to create/update the environment from environment.yml
if ! command -v mfa >/dev/null 2>&1; then
  echo "Note: 'mfa' command not found. Attempting to create/update the 'mfa' environment..."
  if [ ! -f "$REPO_ROOT/environment.yml" ]; then
    echo "ERROR: environment.yml not found in repo root ($REPO_ROOT). Aborting."
    exit 1
  fi
  conda env update -f environment.yml --prune
fi

# Determine how to invoke MFA: either direct 'mfa' or 'conda run -n mfa mfa'
if command -v mfa >/dev/null 2>&1; then
  MFA_CMD="mfa"
else
  MFA_CMD="conda run -n mfa mfa"
fi

echo "Using MFA command: $MFA_CMD"
echo ""

# Prepare corpus directory (copy wav and transcripts only if corpus doesn't already exist)
if [ ! -d "$CORPUS_DIR" ]; then
  echo "Preparing corpus directory..."
  mkdir -p "$CORPUS_DIR"
  # copy wav files
  if compgen -G "$REPO_ROOT/wav/*.wav" >/dev/null; then
    cp -v "$REPO_ROOT"/wav/*.wav "$CORPUS_DIR"/
  else
    echo "Warning: no .wav files found in $REPO_ROOT/wav"
  fi
  # copy transcripts (.txt)
  if compgen -G "$REPO_ROOT/transcripts/*" >/dev/null; then
    cp -v "$REPO_ROOT"/transcripts/* "$CORPUS_DIR"/
  else
    echo "Warning: no transcript files found in $REPO_ROOT/transcripts"
  fi
else
  echo "Corpus directory already exists: $CORPUS_DIR"
fi
echo ""

# Download required models (safe to run repeatedly)
echo "Downloading required MFA models (dictionary, acoustic, g2p). This is idempotent..."
$MFA_CMD model download dictionary "$DICTIONARY_MODEL" || true
$MFA_CMD model download acoustic "$ACOUSTIC_MODEL" || true
$MFA_CMD model download g2p "$G2P_MODEL" || true
echo ""

# Run initial alignment
echo "Running initial alignment (this may take a while)..."
$MFA_CMD align --clean "$CORPUS_DIR" "$DICTIONARY_MODEL" "$ACOUSTIC_MODEL" "$INITIAL_OUTPUT_DIR"
echo "Initial alignment complete -> $INITIAL_OUTPUT_DIR"
echo ""

# Generate OOV dictionary using G2P (back up existing if present)
if [ -f "$OOV_DICT" ]; then
  echo "Found existing OOV dictionary ($OOV_DICT). Backing up to ${OOV_DICT}.bak"
  cp -v "$OOV_DICT" "${OOV_DICT}.bak"
fi

echo "Generating OOV dictionary using G2P model ($G2P_MODEL) from corpus..."
$MFA_CMD g2p "$CORPUS_DIR" "$G2P_MODEL" "$OOV_DICT"
echo "OOV dictionary written to: $OOV_DICT"
echo ""

# Run final alignment using the new OOV dictionary
echo "Running final alignment with OOV dictionary (this may take a while)..."
$MFA_CMD align --clean "$CORPUS_DIR" "$OOV_DICT" "$ACOUSTIC_MODEL" "$FINAL_OUTPUT_DIR"
echo "Final alignment complete -> $FINAL_OUTPUT_DIR"
echo ""

# Quick before/after SPN (unknown/noise phone) check
echo "Computing before/after counts for 'spn' tokens in phone tiers (if present)..."
INIT_SPN_COUNT=0
FINAL_SPN_COUNT=0

if [ -d "$INITIAL_OUTPUT_DIR" ]; then
  # grep may exit with non-zero if no matches; '|| true' avoids failing the script
  INIT_SPN_COUNT=$(grep -o -R 'text = \"spn\"' "$INITIAL_OUTPUT_DIR" 2>/dev/null | wc -l || true)
fi

if [ -d "$FINAL_OUTPUT_DIR" ]; then
  FINAL_SPN_COUNT=$(grep -o -R 'text = \"spn\"' "$FINAL_OUTPUT_DIR" 2>/dev/null | wc -l || true)
fi

echo "Initial 'spn' count: $INIT_SPN_COUNT"
echo "Final   'spn' count: $FINAL_SPN_COUNT"
echo ""

echo "Summary:"
echo "  - Initial results: $INITIAL_OUTPUT_DIR"
echo "  - Final results:   $FINAL_OUTPUT_DIR"
echo "  - OOV dictionary:  $OOV_DICT"
echo ""
echo "You can open the .TextGrid files in Praat to inspect alignments (File -> Open -> Read from file)."
echo "If you want to re-run from scratch, remove the output folders and re-run the script."
echo ""
echo "Done."
