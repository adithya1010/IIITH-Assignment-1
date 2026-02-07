


> Written with [StackEdit](https://stackedit.io/).


# Forced Alignment using Montreal Forced Aligner (MFA)

## 1. Project Overview
This project demonstrates the execution of a complete forced alignment pipeline using the **Montreal Forced Aligner (MFA)** . Forced alignment is an automated process that synchronizes audio recordings with text transcripts at both the word and phoneme levels. This tool determines the precise start and end times for every speech segment in the signal.

## 2. Installation and Setup
The environment is managed using **Conda** to handle the necessary speech processing dependencies.

```bash
# Create the MFA environment
conda create -n mfa -c conda-forge montreal-forced-aligner -y

# Activate the environment
conda activate mfa

# Download the required models and dictionaries
mfa model download dictionary english_us_arpa
mfa model download acoustic english_us_arpa
mfa model download g2p english_us_arpa

```

## 3. Data Preparation

Following the assignment requirements, the dataset was organized into a specific format where each `.wav` audio file is paired with a matching `.txt` transcript file in a single directory.



```
# Create a unified project folder
mkdir my_corpus

# Consolidate audio and transcripts
copy .\wav\*.wav .\my_corpus\
copy .\transcripts\*.txt .\my_corpus\

```

## 4. Execution Pipeline

### Initial Alignment

The first run used the standard `english_us_arpa` dictionary to map known words.



```
mfa align --clean my_corpus english_us_arpa english_us_arpa ./my_alignment_results

```

### Out of Vocabulary (OOV) Solution

To handle words missing from the standard dictionary, a **Grapheme-to-Phoneme (G2P)** model was implemented to predict pronunciations.


# Generate a custom dictionary for OOV words
```bash
mfa g2p my_corpus english_us_arpa my_oov_dictionary.dict
```
# Run final alignment incorporating the new dictionary entries
```bash
mfa align --clean my_corpus my_oov_dictionary.dict english_us_arpa ./my_final_results
```
### Reproducible run (script & environment)

A reproducible script and conda environment file were added to make the pipeline easy to run and reproduce.

- `environment.yml` — conda environment specification (creates an environment named `mfa`). Create/update the environment with:

```bash
conda env update -f environment.yml --prune
```

- `scripts/run_alignment.sh` — convenience script that (when run from the repository root):
  1. creates/updates the `mfa` environment from `environment.yml` (if necessary),
  2. prepares the `my_corpus` directory (copies wav and transcripts),
  3. downloads MFA models (dictionary, acoustic, g2p),
  4. runs the initial alignment -> `my_alignment_results`,
  5. generates `my_oov_dictionary.dict` using G2P,
  6. runs the final alignment -> `my_final_results`,
  7. prints a brief before/after report (e.g., counts of `'spn'` tokens).

Example usage:

```bash
# create/update the conda environment (optional if MFA is already installed)
conda env update -f environment.yml --prune

# run the complete pipeline (from repo root)
bash scripts/run_alignment.sh
```

### Comparison, unit test & running automated tests

A comparison script and a small test wrapper were added to produce a before/after report and (optionally) fail when no improvement is detected.

- `scripts/compare_alignments.py` — analyzes the `TextGrid` outputs and (optionally) the `alignment_analysis.csv` files, and writes:
  - CSV summary: `reports/alignment_comparison.csv`
  - Markdown summary: `reports/alignment_comparison.md`

  Usage:

  ```bash
  python3 scripts/compare_alignments.py --before my_alignment_results --after my_final_results --out-csv reports/alignment_comparison.csv --out-md reports/alignment_comparison.md
  ```

- `scripts/run_comparison.sh` — convenience wrapper that runs the comparison. It supports:
  - `-r, --run-alignments` to re-run the full alignment pipeline (calls `scripts/run_alignment.sh`) before comparing
  - `-f, --fail-on-no-improve` to exit with a non-zero code if no improvement is detected (useful for CI and tests)

  Example usage:

  ```bash
  # run comparison only
  bash scripts/run_comparison.sh

  # run alignments first, then compare and fail if no improvement found
  bash scripts/run_comparison.sh -r -f
  ```

Notes:
- The comparison checks for reductions in `'spn'` tokens and identifies words that were `spn`-only in the initial alignment but received real phones after G2P/dictionary updates (likely OOV fixes).
- The report files are written to `reports/` by default.
- When matplotlib is available, the comparison script will also generate PNG charts in the `reports/` folder and embed them in `reports/alignment_comparison.md`:
  - `alignment_spn_before_after.png` — grouped bars showing 'spn' counts before vs. after per file.
  - `alignment_delta_overall_ll.png` — bar chart of delta overall log-likelihood (after - before) per file.
  - `alignment_fixed_words.png` — horizontal bar chart of top fixed words (spn-only -> phones).
- Use `bash scripts/run_comparison.sh -f` in CI to make the job fail when no improvements are found.

Testing
- A small pytest suite is included at `tests/test_compare_alignments.py`. It covers:
  - parsing a minimal TextGrid (words and phones tiers),
  - counting `'spn'` occurrences,
  - and detecting when a word that was `spn`-only before receives real phones after (i.e., an OOV fix).

To run the tests locally:
```bash
# create/update the reproducible environment (pytest is included in environment.yml)
conda env update -f environment.yml --prune
conda activate mfa

# run the pytest suite
python -m pytest -q
```

- Alternatively, use the comparison wrapper as a basic test (it supports `-f` and will exit non-zero if no improvements are detected):
```bash
bash scripts/run_comparison.sh -f
```


## 5. Inspection and Analysis

The output was verified using **Praat** software to analyze the generated **TextGrid** files.

-   **Word Boundaries:** Marked on Tier 1 (e.g., `0.00-0.45 HELLO`).
    
-   **Phone Boundaries:** Marked on Tier 2 (e.g., `HH`, `AH`, `L`, `OW`).
    

## 6. Key Observations

-   **Boundary Alignment:** Phoneme boundaries generally align with acoustic changes in the waveform.
    
-   **Errors:** Observed minor **timing offsets** where boundaries were slightly shifted from the actual sound onset.
    
-   **OOV Handling:** The implementation of the G2P model successfully allowed words like _dukakis_, _massachusetts_, and _wbur's_ to be aligned, which were initially skipped.
    
    
    

## 7. Project Structure

-   `wav/`: Original audio files.
    
-   `transcripts/`: Original text transcripts.
    
-   `my_final_results/`: Generated TextGrid output files.
    
-   `my_oov_dictionary.dict`: Custom dictionary for handled OOV words.
    
-   `Assignment.pdf`: Project instructions.

## 8. Resources
-   **Montreal Forced Aligner:** [MFA Documentation](https://montreal-forced-aligner.readthedocs.io/)
    
-   **Praat:** [Praat Website](https://www.fon.hum.uva.nl/praat/)
