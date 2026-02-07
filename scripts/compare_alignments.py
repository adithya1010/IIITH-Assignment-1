#!/usr/bin/env python3
"""
Enhanced compare_alignments.py

This script compares Montreal Forced Aligner (MFA) initial and final alignment
outputs (TextGrid files + optional alignment_analysis.csv) and produces:

- A CSV summary (per-file metrics)
- A Markdown summary (human-readable)
- Optional charts (PNG) saved to the same folder as the Markdown report

Key metrics:
- 'spn' counts (before and after)
- percent SPN reduction
- fixed words (spn-only -> real phones)
- deltas in overall log-likelihood, speech log-likelihood, phone duration deviation, and SNR
- counts of words and phones per file

The script is intentionally robust: plotting requires matplotlib; when not
available the script will still produce CSV + Markdown without charts.

Usage example:
    python scripts/compare_alignments.py \
        --before my_alignment_results --after my_final_results \
        --out-csv reports/alignment_comparison.csv \
        --out-md reports/alignment_comparison.md
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Tuple

# Try to import matplotlib for charts; if unavailable we will skip plotting.
HAS_MATPLOTLIB = True
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # type: ignore
except Exception:
    HAS_MATPLOTLIB = False


def parse_args():
    p = argparse.ArgumentParser(
        description="Compare MFA alignments (before vs after) and generate a report"
    )
    p.add_argument(
        "--before",
        "-b",
        default="my_alignment_results",
        help="Directory with initial (before) TextGrid outputs",
    )
    p.add_argument(
        "--after",
        "-a",
        default="my_final_results",
        help="Directory with final (after) TextGrid outputs",
    )
    p.add_argument(
        "--out-csv",
        default=os.path.join("reports", "alignment_comparison.csv"),
        help="CSV summary output",
    )
    p.add_argument(
        "--out-md",
        default=os.path.join("reports", "alignment_comparison.md"),
        help="Markdown report output",
    )
    p.add_argument(
        "--exit-on-no-improve",
        action="store_true",
        help="Exit with code 2 if no improvement found (useful for CI/tests)",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    return p.parse_args()


def read_alignment_analysis_csv(path: str) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Read alignment_analysis.csv and return a dict mapping file -> row.
    Known numeric fields are converted to floats where possible:
      - overall_log_likelihood
      - speech_log_likelihood
      - phone_duration_deviation
      - snr
    """
    metrics: Dict[str, Dict[str, Optional[float]]] = {}
    if not os.path.isfile(path):
        return metrics
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = row.get("file") or row.get("File") or row.get("filename")
            if not key:
                continue
            # convert known numeric fields to floats when possible
            for k in (
                "overall_log_likelihood",
                "speech_log_likelihood",
                "phone_duration_deviation",
                "snr",
            ):
                if k in row:
                    try:
                        row[k] = float(row[k])
                    except Exception:
                        row[k] = None
            metrics[key] = row
    return metrics


def count_spn_in_textgrid(path: str) -> int:
    """Count occurrences of the phone token 'spn' in a TextGrid file."""
    if not path or not os.path.isfile(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except Exception:
        return 0
    return len(re.findall(r'text\s*=\s*"spn"', content))


def parse_textgrid_intervals(path: str) -> Dict[str, List[Tuple[float, float, str]]]:
    """
    Parse a TextGrid file and extract intervals for tiers named 'words' and 'phones'.

    Returns:
        { "words": [(xmin, xmax, text), ...], "phones": [(xmin, xmax, text), ...] }
    """
    if not path or not os.path.isfile(path):
        return {"words": [], "phones": []}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = [ln.rstrip("\n") for ln in fh]
    except Exception:
        return {"words": [], "phones": []}

    tiers: Dict[str, List[Tuple[float, float, str]]] = {}
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        m = re.search(r'name\s*=\s*"([^"]+)"', ln)
        if m:
            tier = m.group(1)
            intervals: List[Tuple[float, float, str]] = []
            j = i + 1
            # move to intervals block
            while j < n and not re.match(r"\s*intervals(\s*\[.*\])?\s*[:=]", lines[j]):
                j += 1
            # parse interval blocks
            while j < n:
                if re.match(r"\s*intervals\s*\[", lines[j]):
                    # parse one interval block
                    j += 1
                    xmin = xmax = None
                    text_val = None
                    while j < n and (xmin is None or xmax is None or text_val is None):
                        l = lines[j].strip()
                        if l.startswith("xmin"):
                            try:
                                xmin = float(l.split("=", 1)[1].strip())
                            except Exception:
                                xmin = 0.0
                        elif l.startswith("xmax"):
                            try:
                                xmax = float(l.split("=", 1)[1].strip())
                            except Exception:
                                xmax = xmin if xmin is not None else 0.0
                        elif l.startswith("text"):
                            t = l.split("=", 1)[1].strip()
                            if t.startswith('"') and t.endswith('"'):
                                t = t[1:-1]
                            text_val = t
                            if xmin is None:
                                xmin = 0.0
                            if xmax is None:
                                xmax = xmin
                            intervals.append((xmin, xmax, text_val))
                            break
                        j += 1
                elif re.match(r"\s*item\s*\[", lines[j]) or re.match(
                    r"\s*class\s*=", lines[j]
                ):
                    break
                else:
                    j += 1
            tiers[tier] = intervals
            i = j
        else:
            i += 1

    words = tiers.get("words") or tiers.get("Words") or tiers.get("word") or []
    phones = tiers.get("phones") or tiers.get("Phones") or tiers.get("phone") or []
    return {"words": words, "phones": phones}


def overlapping_phones_for_word(
    phones: List[Tuple[float, float, str]], wmin: float, wmax: float
) -> List[str]:
    """Return phone labels overlapping a word time span [wmin, wmax]."""
    labels: List[str] = []
    for pmin, pmax, text in phones:
        if pmax > wmin and pmin < wmax:
            labels.append((text or "").strip())
    return labels


def safe_float(val: Optional[object]) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except Exception:
        return None


def analyze(before_dir: str, after_dir: str, verbose: bool = False):
    """
    Analyze 'before' and 'after' alignment outputs.

    Returns:
        rows: list of per-file dictionaries (CSV-ready)
        summary: aggregated summary dict (used for markdown + plotting)
    """

    def list_textgrid_files(directory: str) -> Dict[str, str]:
        if not os.path.isdir(directory):
            return {}
        out: Dict[str, str] = {}
        for fn in os.listdir(directory):
            if fn.lower().endswith(".textgrid"):
                base = os.path.splitext(fn)[0]
                out[base] = os.path.join(directory, fn)
        return out

    before_tgs = list_textgrid_files(before_dir)
    after_tgs = list_textgrid_files(after_dir)
    basenames = sorted(set(before_tgs.keys()) | set(after_tgs.keys()))

    before_analysis = read_alignment_analysis_csv(
        os.path.join(before_dir, "alignment_analysis.csv")
    )
    after_analysis = read_alignment_analysis_csv(
        os.path.join(after_dir, "alignment_analysis.csv")
    )

    rows: List[Dict] = []
    total_before_spn = 0
    total_after_spn = 0
    total_fixed_words = 0
    fixed_word_counter: Counter = Counter()
    files_with_spn_reduction: List[str] = []

    for base in basenames:
        before_tg = before_tgs.get(base)
        after_tg = after_tgs.get(base)

        before_spn = count_spn_in_textgrid(before_tg) if before_tg else 0
        after_spn = count_spn_in_textgrid(after_tg) if after_tg else 0
        total_before_spn += before_spn
        total_after_spn += after_spn

        # parse TextGrids
        before_intervals = (
            parse_textgrid_intervals(before_tg)
            if before_tg
            else {"words": [], "phones": []}
        )
        after_intervals = (
            parse_textgrid_intervals(after_tg)
            if after_tg
            else {"words": [], "phones": []}
        )

        before_words = before_intervals.get("words", [])
        before_phones = before_intervals.get("phones", [])
        after_words = after_intervals.get("words", [])
        after_phones = after_intervals.get("phones", [])

        num_words_before = len([w for w in before_words if (w[2] or "").strip() != ""])
        num_words_after = len([w for w in after_words if (w[2] or "").strip() != ""])
        num_phones_before = len(
            [p for p in before_phones if (p[2] or "").strip() != ""]
        )
        num_phones_after = len([p for p in after_phones if (p[2] or "").strip() != ""])

        # detect fixed words: spn-only before -> real phones after
        fixed_words_here: List[str] = []
        for wxmin, wxmax, wtext in before_words:
            wt = (wtext or "").strip()
            if not wt:
                continue
            bphones = overlapping_phones_for_word(before_phones, wxmin, wxmax)
            aphones = overlapping_phones_for_word(after_phones, wxmin, wxmax)
            bset = set([p.lower() for p in bphones if p.strip() != ""])
            aset = set([p.lower() for p in aphones if p.strip() != ""])
            if bset and bset == {"spn"} and aset and aset != {"spn"}:
                fixed_words_here.append(wt)
                fixed_word_counter[wt] += 1

        n_fixed = len(fixed_words_here)
        total_fixed_words += n_fixed
        if after_spn < before_spn:
            files_with_spn_reduction.append(base)

        before_row = before_analysis.get(base, {})
        after_row = after_analysis.get(base, {})

        before_ll = safe_float(
            before_row.get("overall_log_likelihood") if before_row else None
        )
        after_ll = safe_float(
            after_row.get("overall_log_likelihood") if after_row else None
        )
        before_pdd = safe_float(
            before_row.get("phone_duration_deviation") if before_row else None
        )
        after_pdd = safe_float(
            after_row.get("phone_duration_deviation") if after_row else None
        )
        before_snr = safe_float(before_row.get("snr") if before_row else None)
        after_snr = safe_float(after_row.get("snr") if after_row else None)
        before_speech_ll = safe_float(
            before_row.get("speech_log_likelihood") if before_row else None
        )
        after_speech_ll = safe_float(
            after_row.get("speech_log_likelihood") if after_row else None
        )

        delta_overall_ll = (
            (after_ll - before_ll)
            if (after_ll is not None and before_ll is not None)
            else ""
        )
        delta_pdd = (
            (after_pdd - before_pdd)
            if (after_pdd is not None and before_pdd is not None)
            else ""
        )
        delta_snr = (
            (after_snr - before_snr)
            if (after_snr is not None and before_snr is not None)
            else ""
        )
        delta_speech_ll = (
            (after_speech_ll - before_speech_ll)
            if (after_speech_ll is not None and before_speech_ll is not None)
            else ""
        )

        percent_spn_reduction = (
            round((before_spn - after_spn) / float(before_spn) * 100.0, 2)
            if before_spn > 0
            else 0.0
        )

        row = {
            "file": base,
            "before_spn_count": before_spn,
            "after_spn_count": after_spn,
            "delta_spn": after_spn - before_spn,
            "percent_spn_reduction": percent_spn_reduction,
            "n_fixed_words": n_fixed,
            "fixed_words": ";".join(fixed_words_here),
            "num_words_before": num_words_before,
            "num_words_after": num_words_after,
            "num_phones_before": num_phones_before,
            "num_phones_after": num_phones_after,
            "before_overall_log_likelihood": before_ll if before_ll is not None else "",
            "after_overall_log_likelihood": after_ll if after_ll is not None else "",
            "delta_overall_log_likelihood": delta_overall_ll,
            "before_phone_duration_deviation": before_pdd
            if before_pdd is not None
            else "",
            "after_phone_duration_deviation": after_pdd
            if after_pdd is not None
            else "",
            "delta_phone_duration_deviation": delta_pdd,
            "before_snr": before_snr if before_snr is not None else "",
            "after_snr": after_snr if after_snr is not None else "",
            "delta_snr": delta_snr,
            "before_speech_log_likelihood": before_speech_ll
            if before_speech_ll is not None
            else "",
            "after_speech_log_likelihood": after_speech_ll
            if after_speech_ll is not None
            else "",
            "delta_speech_log_likelihood": delta_speech_ll,
        }
        rows.append(row)
        if verbose:
            print(
                f"Processed {base}: spn {before_spn}->{after_spn}, fixed_words={n_fixed}, words {num_words_before}->{num_words_after}"
            )

    summary = {
        "total_files": len(basenames),
        "total_before_spn": total_before_spn,
        "total_after_spn": total_after_spn,
        "total_spn_delta": total_after_spn - total_before_spn,
        "total_fixed_words": total_fixed_words,
        "files_with_spn_reduction": len(files_with_spn_reduction),
        "files_with_spn_reduction_list": files_with_spn_reduction,
        "top_fixed_words": fixed_word_counter.most_common(20),
        "fixed_word_counter": fixed_word_counter,
    }
    return rows, summary


def write_csv(rows: List[Dict], out_csv: str):
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    fieldnames = [
        "file",
        "before_spn_count",
        "after_spn_count",
        "delta_spn",
        "percent_spn_reduction",
        "n_fixed_words",
        "fixed_words",
        "num_words_before",
        "num_words_after",
        "num_phones_before",
        "num_phones_after",
        "before_overall_log_likelihood",
        "after_overall_log_likelihood",
        "delta_overall_log_likelihood",
        "before_speech_log_likelihood",
        "after_speech_log_likelihood",
        "delta_speech_log_likelihood",
        "before_phone_duration_deviation",
        "after_phone_duration_deviation",
        "delta_phone_duration_deviation",
        "before_snr",
        "after_snr",
        "delta_snr",
    ]
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def generate_plots(rows: List[Dict], summary: Dict, out_dir: str) -> List[str]:
    """
    Generate a few PNG charts (saved in out_dir) and return the list of generated
    image paths. If matplotlib is missing, return an empty list.
    """
    if not HAS_MATPLOTLIB:
        print("matplotlib not available -- skipping chart generation")
        return []

    os.makedirs(out_dir, exist_ok=True)
    files = [r["file"] for r in rows]
    n = len(files)
    x = list(range(n))

    # SPN before/after grouped bar chart
    before_vals = [int(r.get("before_spn_count") or 0) for r in rows]
    after_vals = [int(r.get("after_spn_count") or 0) for r in rows]
    fig, ax = plt.subplots(figsize=(max(6, n * 0.6), 4))
    width = 0.35
    ax.bar(
        [i - width / 2 for i in x], before_vals, width, label="before", color="#6baed6"
    )
    ax.bar(
        [i + width / 2 for i in x], after_vals, width, label="after", color="#fd8d3c"
    )
    ax.set_xticks(x)
    ax.set_xticklabels(files, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("spn count")
    ax.set_title("SPN: before vs after")
    ax.legend()
    fig.tight_layout()
    spn_path = os.path.join(out_dir, "alignment_spn_before_after.png")
    fig.savefig(spn_path, dpi=150)
    plt.close(fig)

    # Delta overall log-likelihood
    delta_ll = []
    for r in rows:
        v = r.get("delta_overall_log_likelihood")
        try:
            delta_ll.append(float(v) if v != "" and v is not None else 0.0)
        except Exception:
            delta_ll.append(0.0)
    fig, ax = plt.subplots(figsize=(max(6, n * 0.6), 4))
    ax.bar(x, delta_ll, color="#74c476")
    ax.set_xticks(x)
    ax.set_xticklabels(files, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("delta overall log-likelihood")
    ax.set_title("Delta overall log-likelihood (after - before)")
    fig.tight_layout()
    delta_ll_path = os.path.join(out_dir, "alignment_delta_overall_ll.png")
    fig.savefig(delta_ll_path, dpi=150)
    plt.close(fig)

    # Top fixed words (horizontal bar chart)
    top_fixed = summary.get("top_fixed_words", [])[:20]
    fixed_words_img = None
    if top_fixed:
        words = [w for w, c in top_fixed]
        counts = [c for w, c in top_fixed]
        fig, ax = plt.subplots(figsize=(6, max(3, len(words) * 0.3)))
        ax.barh(list(reversed(words)), list(reversed(counts)), color="#9e9ac8")
        ax.set_xlabel("fix count")
        ax.set_title("Top fixed words (spn-only -> phones)")
        fig.tight_layout()
        fixed_words_img = os.path.join(out_dir, "alignment_fixed_words.png")
        fig.savefig(fixed_words_img, dpi=150)
        plt.close(fig)

    images = [spn_path, delta_ll_path]
    if fixed_words_img:
        images.append(fixed_words_img)
    images = [p for p in images if p and os.path.exists(p)]
    return images


def write_markdown(rows: List[Dict], summary: Dict, out_md: str):
    os.makedirs(os.path.dirname(out_md) or ".", exist_ok=True)
    out_dir = os.path.dirname(out_md) or "."
    # Attempt to produce charts (if matplotlib available); the function will skip if not
    images = generate_plots(rows, summary, out_dir)

    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write("# Alignment Comparison Report\n\n")
        fh.write("## Summary\n\n")
        fh.write(f"- Total files processed: **{summary['total_files']}**\n")
        fh.write(f"- Total 'spn' tokens (before): **{summary['total_before_spn']}**\n")
        fh.write(f"- Total 'spn' tokens (after):  **{summary['total_after_spn']}**\n")
        fh.write(f"- Delta 'spn' (after - before): **{summary['total_spn_delta']}**\n")
        fh.write(
            f"- Total fixed words (spn-only -> real phones): **{summary['total_fixed_words']}**\n"
        )
        fh.write(
            f"- Files with spn reduction: **{summary['files_with_spn_reduction']}**\n\n"
        )

        fh.write("### Top fixed words (most frequent)\n\n")
        if summary["top_fixed_words"]:
            fh.write("| Word | Count |\n")
            fh.write("| ---- | -----:|\n")
            for w, c in summary["top_fixed_words"]:
                fh.write(f"| {w} | {c} |\n")
        else:
            fh.write("No fixed words detected.\n")
        fh.write("\n---\n\n")

        if images:
            fh.write("## Charts\n\n")
            for img in images:
                fh.write(f"![{os.path.basename(img)}]({os.path.basename(img)})\n\n")

        fh.write("## Per-file details\n\n")
        fh.write(
            "| file | before_spn | after_spn | delta_spn | percent_spn_reduction | n_fixed_words | fixed_words | before_ll | after_ll | delta_ll |\n"
        )
        fh.write(
            "| ---- | ---------: | --------: | --------: | -------------------: | -------------: | ----------- | ---------: | -------: | -------: |\n"
        )
        for r in rows:
            fh.write(
                "| {file} | {before_spn_count} | {after_spn_count} | {delta_spn} | {percent_spn_reduction} | {n_fixed_words} | {fixed_words} | {before_overall_log_likelihood} | {after_overall_log_likelihood} | {delta_overall_log_likelihood} |\n".format(
                    **r
                )
            )


def main():
    args = parse_args()
    rows, summary = analyze(args.before, args.after, verbose=args.verbose)

    # write CSV
    write_csv(rows, args.out_csv)
    if args.verbose:
        print(f"Wrote CSV: {args.out_csv}")

    # write Markdown (this will also attempt to create charts)
    write_markdown(rows, summary, args.out_md)
    if args.verbose:
        print(f"Wrote Markdown summary: {args.out_md}")

    # print short summary
    print("=== Alignment comparison summary ===")
    print(f"Files processed: {summary['total_files']}")
    print(
        f"Total 'spn' before -> after: {summary['total_before_spn']} -> {summary['total_after_spn']} (delta {summary['total_spn_delta']})"
    )
    print(f"Total fixed words detected: {summary['total_fixed_words']}")
    if summary["top_fixed_words"]:
        top = summary["top_fixed_words"][:5]
        print("Top fixed words:", ", ".join(f"{w} ({c})" for w, c in top))

    improved = (summary["total_after_spn"] < summary["total_before_spn"]) or (
        summary["total_fixed_words"] > 0
    )
    if args.exit_on_no_improve and not improved:
        print(
            "No improvement detected (exit-on-no-improve requested). Exiting with code 2."
        )
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
