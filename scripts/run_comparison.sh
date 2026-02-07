#!/usr/bin/env bash
# run_comparison.sh
#
# Wrapper to run the alignment comparison script and optionally run the alignment pipeline first.
# Produces a CSV and Markdown summary (defaults: reports/alignment_comparison.csv, reports/alignment_comparison.md)
#
# Usage:
#   bash scripts/run_comparison.sh [options]
#
# Options:
#   -r, --run-alignments         Run the full alignment pipeline (scripts/run_alignment.sh) before comparing
#   -f, --fail-on-no-improve     Exit non-zero when no improvement detected (useful for CI)
#   --before DIR                 Directory with initial (before) TextGrids (default: my_alignment_results)
#   --after DIR                  Directory with final (after) TextGrids (default: my_final_results)
#   --out-csv FILE               Output CSV path (default: reports/alignment_comparison.csv)
#   --out-md FILE                Output Markdown path (default: reports/alignment_comparison.md)
#   --python CMD                 Python executable to use (default: python3 or python)
#   -h, --help                   Show this help and exit
#
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Defaults
RUN_ALIGNMENTS=false
FAIL_ON_NO_IMPROVE=false
BEFORE="$REPO_ROOT/my_alignment_results"
AFTER="$REPO_ROOT/my_final_results"
OUT_CSV="$REPO_ROOT/reports/alignment_comparison.csv"
OUT_MD="$REPO_ROOT/reports/alignment_comparison.md"
PYTHON_CMD=""

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Options:
  -r, --run-alignments         Run the full alignment pipeline (scripts/run_alignment.sh) before comparing
  -f, --fail-on-no-improve     Exit non-zero when no improvement detected (useful for CI)
  --before DIR                 Directory with initial (before) TextGrids (default: $BEFORE)
  --after DIR                  Directory with final (after) TextGrids (default: $AFTER)
  --out-csv FILE               Output CSV path (default: $OUT_CSV)
  --out-md FILE                Output Markdown path (default: $OUT_MD)
  --python CMD                 Python executable to use (default: try python3 then python)
  -h, --help                   Show this help and exit

Example:
  # run comparison only
  bash scripts/run_comparison.sh

  # (re)run alignments first, then compare and fail if no improvement
  bash scripts/run_comparison.sh -r -f
USAGE
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--run-alignments)
      RUN_ALIGNMENTS=true
      shift
      ;;
    -f|--fail-on-no-improve)
      FAIL_ON_NO_IMPROVE=true
      shift
      ;;
    --before)
      BEFORE="$2"; shift 2
      ;;
    --after)
      AFTER="$2"; shift 2
      ;;
    --out-csv)
      OUT_CSV="$2"; shift 2
      ;;
    --out-md)
      OUT_MD="$2"; shift 2
      ;;
    --python)
      PYTHON_CMD="$2"; shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

# Find python executable if not provided
if [[ -z "$PYTHON_CMD" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
  else
    echo "ERROR: python not found. Please install Python 3 and ensure it's in PATH."
    exit 1
  fi
fi

# Optionally run the alignment pipeline first
if $RUN_ALIGNMENTS ; then
  if [[ -x "$REPO_ROOT/scripts/run_alignment.sh" ]]; then
    echo "Running alignment pipeline (this may take a while)..."
    bash "$REPO_ROOT/scripts/run_alignment.sh"
  else
    echo "ERROR: scripts/run_alignment.sh not found or not executable."
    exit 1
  fi
fi

# Ensure compare script exists
COMPARE_PY="$REPO_ROOT/scripts/compare_alignments.py"
if [[ ! -f "$COMPARE_PY" ]]; then
  echo "ERROR: compare script not found: $COMPARE_PY"
  exit 1
fi

# Prepare args for python script
PY_ARGS=(--before "$BEFORE" --after "$AFTER" --out-csv "$OUT_CSV" --out-md "$OUT_MD")
if $FAIL_ON_NO_IMPROVE ; then
  PY_ARGS+=(--exit-on-no-improve)
fi

echo "Running comparison:"
echo "  before: $BEFORE"
echo "  after:  $AFTER"
echo "  out-csv: $OUT_CSV"
echo "  out-md:  $OUT_MD"
echo ""

set +e
"$PYTHON_CMD" "$COMPARE_PY" "${PY_ARGS[@]}"
PY_RC=$?
set -e

# Show a short snippet of the generated Markdown summary if available
if [[ -f "$OUT_MD" ]]; then
  echo ""
  echo "=== Summary (first 20 lines of $OUT_MD) ==="
  head -n 20 "$OUT_MD" || true
  echo "=========================================="
  echo ""
else
  echo "Warning: Markdown summary not found at $OUT_MD"
fi

# Interpret exit code
if [[ $PY_RC -eq 0 ]]; then
  echo "PASS: improvements detected or comparison completed successfully."
  exit 0
elif [[ $PY_RC -eq 2 ]]; then
  echo "No improvement detected by comparison."
  if $FAIL_ON_NO_IMPROVE ; then
    echo "Failing (exit-on-no-improve enabled). Exiting with code 2."
    exit 2
  else
    echo "Not failing (use --fail-on-no-improve to make this a failing condition)."
    exit 0
  fi
else
  echo "Comparison script finished with unexpected exit code: $PY_RC"
  exit $PY_RC
fi
