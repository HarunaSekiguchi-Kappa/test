import csv
import re
import sys
from pathlib import Path


def clean_doi(doi: str) -> str:
    """Remove common trailing punctuation accidentally captured from citations."""
    if not doi:
        return ""
    doi = doi.strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    # Remove trailing punctuation that is usually not part of DOI in references.
    doi = doi.rstrip(".,;)")
    return doi


def normalize_text(text: str) -> str:
    """Normalize common unicode variants that appear in copied reference lists."""
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("：", ":")
    text = text.replace(" ", " ")
    text = text.replace("–", "-")
    return text


def split_records(text: str) -> list[str]:
    """
    Split raw reference text into one block per paper.

    Preferred format:
      論文1:
      citation...
      論文2:
      citation...

    It also supports:
      Paper 1:
      citation...
      Paper 2:
      citation...

    If no labels are found, it falls back to splitting by blank lines.
    """
    text = normalize_text(text)

    pattern = re.compile(r"(?im)^\s*(?:論文|paper)\s*\d+\s*:\s*")
    matches = list(pattern.finditer(text))

    if matches:
        records = []
        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block = text[start:end].strip()
            if block:
                records.append(block)
        return records

    # Fallback: split by 2+ newlines if labels are not present.
    return [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]


def extract_ids(block: str) -> dict:
    """
    Extract PMID / PMCID / DOI from one citation block.
    """
    pmid = ""
    pmcid = ""
    doi = ""

    pmid_match = re.search(r"(?:PubMed\s*)?PMID\s*:?\s*(\d+)", block, flags=re.I)
    if pmid_match:
        pmid = pmid_match.group(1).strip()

    pmcid_match = re.search(r"(?:PubMed\s+Central\s*)?PMCID\s*:?\s*(PMC\d+)", block, flags=re.I)
    if pmcid_match:
        pmcid = pmcid_match.group(1).strip().upper()
    else:
        # Fallback: any PMC ID in the text
        pmcid_match = re.search(r"\b(PMC\d+)\b", block, flags=re.I)
        if pmcid_match:
            pmcid = pmcid_match.group(1).strip().upper()

    doi_match = re.search(
        r"(?:doi\s*:?\s*|https?://doi\.org/)(10\.\d{4,9}/[^\s;]+)",
        block,
        flags=re.I,
    )
    if doi_match:
        doi = clean_doi(doi_match.group(1))

    return {
        "pmid": pmid,
        "pmcid": pmcid,
        "doi": doi,
        "citation": " ".join(block.split()),
    }


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage:")
        print("  python raw_to_input_papers_csv.py input_raw.txt input_papers.csv")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    text = input_path.read_text(encoding="utf-8")
    blocks = split_records(text)

    rows = []
    for idx, block in enumerate(blocks, start=1):
        row = extract_ids(block)
        row["paper_index"] = idx
        warnings = []
        if not row["pmid"]:
            warnings.append("PMID not found")
        if not row["pmcid"]:
            warnings.append("PMCID not found")
        if not row["doi"]:
            warnings.append("DOI not found")
        row["warnings"] = "; ".join(warnings)
        rows.append(row)

    fieldnames = ["paper_index", "pmid", "pmcid", "doi", "citation", "warnings"]
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved: {output_path}")
    print(f"Extracted records: {len(rows)}")
    print()
    print("Preview:")
    for row in rows[:20]:
        print(
            f'{row["paper_index"]}. '
            f'PMID={row["pmid"] or "-"} '
            f'PMCID={row["pmcid"] or "-"} '
            f'DOI={row["doi"] or "-"} '
            f'Warnings={row["warnings"] or "-"}'
        )


if __name__ == "__main__":
    main()
