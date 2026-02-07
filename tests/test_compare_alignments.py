# tests for compare_alignments.py
# These pytest tests validate a few edge cases:
#  - parsing of a minimal TextGrid (words + phones)
#  - detection/counting of 'spn' tokens
#  - detection of a word that was spn-only in 'before' and receives real phones in 'after'
#
# The tests import the compare_alignments module directly by path so they can run
# without needing the package to be installed.

import importlib.util
import os
import textwrap

import pytest


def load_compare_module():
    """
    Dynamically load the compare_alignments.py module from the repository's scripts/ folder.
    This keeps tests robust even when the package is not installed.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    module_path = os.path.join(repo_root, "scripts", "compare_alignments.py")
    spec = importlib.util.spec_from_file_location("compare_alignments", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_textgrid(path, intervals_words, intervals_phones):
    """
    Write a minimal TextGrid file with a 'words' tier and a 'phones' tier.
    intervals_words and intervals_phones are lists of tuples: (xmin, xmax, text)
    """
    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        "xmin = 0",
        "xmax = 1",
        "tiers? <exists>",
        "size = 2",
        "item []:",
        "    item [1]:",
        '        class = "IntervalTier"',
        '        name = "words"',
        "        xmin = 0",
        "        xmax = 1",
        f"        intervals: size = {len(intervals_words)}",
    ]
    for i, (xmin, xmax, text) in enumerate(intervals_words, start=1):
        lines += [
            f"        intervals [{i}]:",
            f"            xmin = {xmin}",
            f"            xmax = {xmax}",
            f'            text = "{text}"',
        ]
    lines += [
        "    item [2]:",
        '        class = "IntervalTier"',
        '        name = "phones"',
        "        xmin = 0",
        "        xmax = 1",
        f"        intervals: size = {len(intervals_phones)}",
    ]
    for i, (xmin, xmax, text) in enumerate(intervals_phones, start=1):
        lines += [
            f"        intervals [{i}]:",
            f"            xmin = {xmin}",
            f"            xmax = {xmax}",
            f'            text = "{text}"',
        ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def test_parse_textgrid_and_count_spn(tmp_path):
    module = load_compare_module()
    tg = tmp_path / "sample.TextGrid"
    write_textgrid(str(tg), [(0.0, 1.0, "hello")], [(0.0, 1.0, "spn")])

    parsed = module.parse_textgrid_intervals(str(tg))
    assert "words" in parsed and "phones" in parsed
    assert parsed["words"][0][2] == "hello"
    assert parsed["phones"][0][2] == "spn"
    assert module.count_spn_in_textgrid(str(tg)) == 1


def test_missing_tiers(tmp_path):
    module = load_compare_module()
    tg = tmp_path / "missing_phones.TextGrid"
    # Create TextGrid with words tier but no phones tier
    content = textwrap.dedent(
        """\
        File type = "ooTextFile"
        Object class = "TextGrid"
        xmin = 0
        xmax = 1
        tiers? <exists>
        size = 1
        item []:
            item [1]:
                class = "IntervalTier"
                name = "words"
                xmin = 0
                xmax = 1
                intervals: size = 1
                intervals [1]:
                    xmin = 0.0
                    xmax = 1.0
                    text = "onlyword"
        """
    )
    with open(tg, "w", encoding="utf-8") as fh:
        fh.write(content)

    parsed = module.parse_textgrid_intervals(str(tg))
    # phones may be empty list
    assert "words" in parsed
    assert parsed["words"][0][2] == "onlyword"
    assert parsed["phones"] == []


def test_analyze_detects_fixed_word(tmp_path):
    module = load_compare_module()
    before_dir = tmp_path / "before"
    after_dir = tmp_path / "after"
    before_dir.mkdir()
    after_dir.mkdir()

    # before: word 'test' aligned with spn-only
    write_textgrid(
        str(before_dir / "utt1.TextGrid"), [(0.0, 1.0, "test")], [(0.0, 1.0, "spn")]
    )

    # after: same word, phones are real phones
    phones_after = [
        (0.0, 0.25, "T"),
        (0.25, 0.5, "EH"),
        (0.5, 0.75, "S"),
        (0.75, 1.0, "T"),
    ]
    write_textgrid(str(after_dir / "utt1.TextGrid"), [(0.0, 1.0, "test")], phones_after)

    rows, summary = module.analyze(str(before_dir), str(after_dir), verbose=False)
    # find row for utt1
    matched = [r for r in rows if r["file"] == "utt1"]
    assert matched, "utt1 should be present in analysis rows"
    row = matched[0]
    assert row["n_fixed_words"] >= 1
    assert "test" in row["fixed_words"]

    # new metrics introduced: percent_spn_reduction should be 100.0 in this case
    assert float(row.get("percent_spn_reduction", 0)) == 100.0
    # counts should be present and sensible
    assert row.get("num_words_before", 0) >= 1
    assert row.get("num_phones_before", 0) >= 1
    assert row.get("num_phones_after", 0) >= 1
