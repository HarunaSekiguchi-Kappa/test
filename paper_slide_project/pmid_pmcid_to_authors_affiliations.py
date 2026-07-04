#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PMID / PMCID / DOI / citation から、PubMed XML / PMC JATS XML を使って
著者・所属を抽出し、CSVに出力するスクリプト。

使い方:
  python pmid_pmcid_to_authors_affiliations.py input_papers.csv authors_affiliations.csv

入力CSVの例1:
  pmid,pmcid,doi
  35854720,PMC9285174,

入力CSVの例2:
  citation
  Phuong J, Hong S, ... PubMed PMID: 35854720; PubMed Central PMCID: PMC9285174.

出力:
  authors_affiliations.csv          著者ごとに1行
  authors_affiliations_summary.csv  論文ごとに1行。papers.json用の authors / affiliations に近い形式

環境変数（任意）:
  NCBI_EMAIL     NCBIへの問い合わせに付けるメールアドレス
  NCBI_API_KEY   NCBI API Key。大量実行時に推奨
  NCBI_TOOL      ツール名。未設定なら既定値を使う
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


TOOL = os.getenv("NCBI_TOOL", "paper_slide_author_affiliation_extractor")
EMAIL = os.getenv("NCBI_EMAIL", "")
API_KEY = os.getenv("NCBI_API_KEY", "")
REQUEST_DELAY_SECONDS = 0.12 if API_KEY else 0.34

SUPERSCRIPT_TRANS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


# -----------------------------
# Utility
# -----------------------------

def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clean_doi(doi: str) -> str:
    doi = (doi or "").strip()
    doi = re.sub(r"^(?:doi\s*:?\s*)", "", doi, flags=re.I)
    doi = doi.rstrip(".;,)］]}")
    return doi


def to_superscript_number(num: int) -> str:
    return str(num).translate(SUPERSCRIPT_TRANS)


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def child_text(elem: ET.Element, name: str) -> str:
    child = elem.find(name)
    if child is None or child.text is None:
        return ""
    return normalize_space(child.text)


def iter_descendants_by_local_name(elem: ET.Element, wanted: str) -> Iterable[ET.Element]:
    for x in elem.iter():
        if local_name(x.tag) == wanted:
            yield x


def find_first_descendant(elem: ET.Element, wanted: str) -> Optional[ET.Element]:
    for x in iter_descendants_by_local_name(elem, wanted):
        return x
    return None


def collect_text_excluding(elem: ET.Element, excluded_local_names: set[str]) -> str:
    parts: List[str] = []

    def walk(node: ET.Element) -> None:
        if local_name(node.tag) in excluded_local_names:
            if node.tail:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in list(node):
            walk(child)
        if node.tail:
            parts.append(node.tail)

    walk(elem)
    return normalize_space(" ".join(parts))


def http_get(url: str, params: Optional[Dict[str, str]] = None, retries: int = 3) -> bytes:
    if params:
        url = url + "?" + urlencode(params)

    headers = {
        "User-Agent": f"{TOOL}/1.0 ({EMAIL or 'no-email-provided'})",
    }

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as resp:
                data = resp.read()
            time.sleep(REQUEST_DELAY_SECONDS)
            return data
        except (HTTPError, URLError, TimeoutError) as e:
            last_error = e
            wait = min(2 * attempt, 8)
            time.sleep(wait)

    raise RuntimeError(f"HTTP request failed after {retries} tries: {url}\n{last_error}")


# -----------------------------
# Input parsing / identifier resolution
# -----------------------------

def extract_ids_from_text(text: str) -> Dict[str, str]:
    text = text or ""
    out: Dict[str, str] = {"pmid": "", "pmcid": "", "doi": ""}

    m = re.search(r"(?:PubMed\s*)?PMID\s*:?\s*(\d{5,})", text, flags=re.I)
    if m:
        out["pmid"] = m.group(1)

    m = re.search(r"\b(PMC\d+)\b", text, flags=re.I)
    if m:
        out["pmcid"] = m.group(1).upper()

    # DOIは空白・セミコロン・PMIDなどの手前まで拾う
    m = re.search(r"\bdoi\s*:?\s*(10\.\d{4,9}/[^\s;]+)", text, flags=re.I)
    if not m:
        m = re.search(r"\b(10\.\d{4,9}/[^\s;]+)", text, flags=re.I)
    if m:
        out["doi"] = clean_doi(m.group(1))

    return out


def read_input_rows(input_path: Path) -> List[Dict[str, str]]:
    with open(input_path, "r", encoding="utf-8-sig", newline="") as f:
        first_line = f.readline()
        f.seek(0)

        # ヘッダーありCSVとして読む
        possible_header = [x.strip().lower() for x in first_line.split(",")]
        known = {"pmid", "pmcid", "doi", "citation"}
        if any(x in known for x in possible_header):
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                normalized = {str(k).strip().lower(): (v or "").strip() for k, v in row.items()}
                rows.append(normalized)
            return rows

        # ヘッダーなし：1列目をcitationとして扱う
        reader = csv.reader(f)
        rows = []
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            rows.append({"citation": row[0].strip()})
        return rows


def resolve_ids(row: Dict[str, str]) -> Dict[str, str]:
    citation_ids = extract_ids_from_text(row.get("citation", ""))

    pmid = (row.get("pmid") or citation_ids.get("pmid") or "").strip()
    pmcid = (row.get("pmcid") or citation_ids.get("pmcid") or "").strip().upper()
    doi = clean_doi(row.get("doi") or citation_ids.get("doi") or "")

    # PMID/PMCID/DOIの相互変換で足りないIDを補う
    candidate = pmid or pmcid or doi
    if candidate:
        try:
            converted = id_converter(candidate)
            pmid = pmid or converted.get("pmid", "")
            pmcid = pmcid or converted.get("pmcid", "")
            doi = doi or converted.get("doi", "")
        except Exception:
            # 変換できなくても、すでにあるIDで続行する
            pass

    return {"pmid": pmid, "pmcid": pmcid, "doi": doi}


def id_converter(identifier: str) -> Dict[str, str]:
    # PMC公式のID Converter API
    url = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
    params = {
        "ids": identifier,
        "format": "json",
        "tool": TOOL,
    }
    if EMAIL:
        params["email"] = EMAIL

    data = http_get(url, params=params)
    payload = json.loads(data.decode("utf-8"))

    records = payload.get("records") or []
    if not records:
        return {"pmid": "", "pmcid": "", "doi": ""}

    record = records[0]
    return {
        "pmid": str(record.get("pmid") or ""),
        "pmcid": str(record.get("pmcid") or ""),
        "doi": clean_doi(str(record.get("doi") or "")),
    }


# -----------------------------
# PubMed XML extraction
# -----------------------------

def fetch_pubmed_xml(pmid: str) -> bytes:
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
        "tool": TOOL,
    }
    if EMAIL:
        params["email"] = EMAIL
    if API_KEY:
        params["api_key"] = API_KEY
    return http_get(url, params=params)


def parse_pubmed_xml(xml_bytes: bytes) -> Tuple[List[Dict], Dict[str, str], List[str]]:
    warnings: List[str] = []
    root = ET.fromstring(xml_bytes)
    article = root.find(".//PubmedArticle")
    if article is None:
        raise ValueError("PubMedArticle not found in PubMed XML")

    ids = {"pmid": "", "pmcid": "", "doi": ""}
    pmid_elem = article.find(".//MedlineCitation/PMID")
    if pmid_elem is not None and pmid_elem.text:
        ids["pmid"] = pmid_elem.text.strip()

    for aid in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        id_type = (aid.attrib.get("IdType") or "").lower()
        value = normalize_space(aid.text or "")
        if id_type == "pmc":
            ids["pmcid"] = value
        elif id_type == "doi":
            ids["doi"] = clean_doi(value)

    authors: List[Dict] = []
    for order, author in enumerate(article.findall(".//MedlineCitation/Article/AuthorList/Author"), start=1):
        collective = child_text(author, "CollectiveName")
        last = child_text(author, "LastName")
        fore = child_text(author, "ForeName")
        initials = child_text(author, "Initials")
        suffix = child_text(author, "Suffix")

        if collective:
            name = collective
        elif fore and last:
            name = f"{fore} {last}"
        elif initials and last:
            name = f"{initials} {last}"
        elif last:
            name = last
        else:
            name = ""

        if suffix:
            name = f"{name} {suffix}"

        affs = []
        for aff in author.findall("./AffiliationInfo/Affiliation"):
            text = normalize_space(aff.text or "")
            if text and text not in affs:
                affs.append(text)

        if name:
            authors.append({"order": order, "name": name, "affiliations": affs})

    if authors and not any(a["affiliations"] for a in authors):
        warnings.append("No author affiliations found in PubMed XML")

    return authors, ids, warnings


# -----------------------------
# PMC JATS XML extraction
# -----------------------------

def fetch_pmc_xml(pmcid: str) -> bytes:
    # pmc.ncbi.nlm.nih.gov の ?report=xml は、JATS XMLが取得できる論文で有効なことが多い。
    pmcid = pmcid.upper()
    urls = [
        f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/?report=xml",
        f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/?report=xml",
    ]
    last_error: Optional[Exception] = None
    for url in urls:
        try:
            return http_get(url)
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Could not fetch PMC XML for {pmcid}: {last_error}")


def aff_text_from_jats_aff(aff_elem: ET.Element) -> str:
    # <label>1</label> は所属本文ではなく番号なので除外する
    return collect_text_excluding(aff_elem, {"label"})


def parse_pmc_jats_xml(xml_bytes: bytes) -> Tuple[List[Dict], Dict[str, str], List[str]]:
    warnings: List[str] = []
    root = ET.fromstring(xml_bytes)
    if local_name(root.tag) != "article":
        raise ValueError("PMC XML root is not <article>")

    article_meta = find_first_descendant(root, "article-meta")
    if article_meta is None:
        raise ValueError("article-meta not found in PMC JATS XML")

    ids = {"pmid": "", "pmcid": "", "doi": ""}
    for aid in iter_descendants_by_local_name(article_meta, "article-id"):
        pub_id_type = (aid.attrib.get("pub-id-type") or "").lower()
        value = normalize_space("".join(aid.itertext()))
        if pub_id_type == "pmid":
            ids["pmid"] = value
        elif pub_id_type == "pmc":
            ids["pmcid"] = "PMC" + value if value.isdigit() else value.upper()
        elif pub_id_type == "doi":
            ids["doi"] = clean_doi(value)

    # aff id -> affiliation text
    aff_by_id: Dict[str, str] = {}
    for aff in iter_descendants_by_local_name(article_meta, "aff"):
        aff_id = aff.attrib.get("id") or aff.attrib.get("{http://www.w3.org/XML/1998/namespace}id") or ""
        aff_text = aff_text_from_jats_aff(aff)
        if aff_id and aff_text:
            aff_by_id[aff_id] = aff_text

    # contrib-group 内の author を抽出
    authors: List[Dict] = []
    contribs = []
    for contrib_group in iter_descendants_by_local_name(article_meta, "contrib-group"):
        for child in list(contrib_group):
            if local_name(child.tag) == "contrib":
                contribs.append(child)

    for order, contrib in enumerate(contribs, start=1):
        ctype = (contrib.attrib.get("contrib-type") or "").lower()
        if ctype and ctype != "author":
            continue

        collab = None
        for x in list(contrib):
            if local_name(x.tag) == "collab":
                collab = normalize_space("".join(x.itertext()))
                break

        name_elem = None
        for x in list(contrib):
            if local_name(x.tag) == "name":
                name_elem = x
                break

        if collab:
            name = collab
        elif name_elem is not None:
            surname = ""
            given = ""
            suffix = ""
            for x in list(name_elem):
                lname = local_name(x.tag)
                value = normalize_space("".join(x.itertext()))
                if lname == "surname":
                    surname = value
                elif lname == "given-names":
                    given = value
                elif lname == "suffix":
                    suffix = value
            name = normalize_space(f"{given} {surname} {suffix}")
        else:
            name = ""

        # 著者に紐づく所属ID
        rids: List[str] = []
        for xref in iter_descendants_by_local_name(contrib, "xref"):
            ref_type = (xref.attrib.get("ref-type") or "").lower()
            rid_raw = xref.attrib.get("rid") or ""
            if ref_type == "aff" and rid_raw:
                for rid in rid_raw.split():
                    if rid not in rids:
                        rids.append(rid)

        affs = []
        for rid in rids:
            text = aff_by_id.get(rid, "")
            if text and text not in affs:
                affs.append(text)

        # contribの中に直接affが入っているケースも拾う
        for aff in iter_descendants_by_local_name(contrib, "aff"):
            text = aff_text_from_jats_aff(aff)
            if text and text not in affs:
                affs.append(text)

        if name:
            authors.append({"order": len(authors) + 1, "name": name, "affiliations": affs})

    if authors and not any(a["affiliations"] for a in authors):
        warnings.append("No author-affiliation links found in PMC JATS XML")

    return authors, ids, warnings


# -----------------------------
# Formatting / output
# -----------------------------

def deduplicate_and_number_affiliations(authors: List[Dict]) -> Tuple[str, str, List[Dict]]:
    aff_to_num: "OrderedDict[str, int]" = OrderedDict()
    enriched: List[Dict] = []

    for author in authors:
        nums: List[int] = []
        unique_author_affs: List[str] = []
        for aff in author.get("affiliations", []):
            aff = normalize_space(aff)
            if not aff:
                continue
            if aff not in aff_to_num:
                aff_to_num[aff] = len(aff_to_num) + 1
            num = aff_to_num[aff]
            if num not in nums:
                nums.append(num)
            if aff not in unique_author_affs:
                unique_author_affs.append(aff)

        enriched_author = dict(author)
        enriched_author["affiliation_numbers"] = nums
        enriched_author["affiliations"] = unique_author_affs
        enriched.append(enriched_author)

    formatted_author_parts = []
    for author in enriched:
        marker = "".join(to_superscript_number(n) for n in author.get("affiliation_numbers", []))
        if marker:
            formatted_author_parts.append(f"{author['name']} {marker}")
        else:
            formatted_author_parts.append(author["name"])
    authors_formatted = ", ".join(formatted_author_parts)

    affiliations_lines = []
    for aff, num in aff_to_num.items():
        affiliations_lines.append(f"{to_superscript_number(num)}{aff}")
    affiliations_formatted = "\n".join(affiliations_lines)

    return authors_formatted, affiliations_formatted, enriched


def choose_best_source(pmid: str, pmcid: str) -> Tuple[List[Dict], Dict[str, str], str, List[str]]:
    all_warnings: List[str] = []

    # 1) PMCIDがある場合はPMC JATS XMLを優先
    if pmcid:
        try:
            pmc_xml = fetch_pmc_xml(pmcid)
            authors, ids, warnings = parse_pmc_jats_xml(pmc_xml)
            all_warnings.extend(warnings)
            if authors and any(a.get("affiliations") for a in authors):
                return authors, ids, "pmc_jats_xml", all_warnings
            # 著者は取れたが所属リンクがない場合はPubMedへフォールバック
            if authors:
                all_warnings.append("PMC JATS XML parsed but affiliations were insufficient; fell back to PubMed XML")
        except Exception as e:
            all_warnings.append(f"PMC JATS XML failed: {e}")

    # 2) PubMed XMLを使う
    if not pmid:
        return [], {"pmid": pmid, "pmcid": pmcid, "doi": ""}, "none", all_warnings + ["No PMID available"]

    try:
        pubmed_xml = fetch_pubmed_xml(pmid)
        authors, ids, warnings = parse_pubmed_xml(pubmed_xml)
        all_warnings.extend(warnings)
        return authors, ids, "pubmed_xml", all_warnings
    except Exception as e:
        all_warnings.append(f"PubMed XML failed: {e}")
        return [], {"pmid": pmid, "pmcid": pmcid, "doi": ""}, "none", all_warnings


def process(input_path: Path, output_path: Path) -> None:
    rows = read_input_rows(input_path)
    if not rows:
        raise ValueError("Input CSV has no rows")

    detail_rows: List[Dict[str, str]] = []
    summary_rows: List[Dict[str, str]] = []

    for paper_index, row in enumerate(rows, start=1):
        ids = resolve_ids(row)
        pmid = ids.get("pmid", "")
        pmcid = ids.get("pmcid", "")
        doi = ids.get("doi", "")

        print(f"[{paper_index}/{len(rows)}] PMID={pmid or '-'} PMCID={pmcid or '-'} DOI={doi or '-'}")

        authors, parsed_ids, source, warnings = choose_best_source(pmid, pmcid)
        pmid = parsed_ids.get("pmid") or pmid
        pmcid = parsed_ids.get("pmcid") or pmcid
        doi = parsed_ids.get("doi") or doi

        authors_formatted, affiliations_formatted, enriched_authors = deduplicate_and_number_affiliations(authors)
        warnings_text = " | ".join(warnings)

        if not enriched_authors:
            detail_rows.append({
                "paper_index": str(paper_index),
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "source": source,
                "author_order": "",
                "author_name": "",
                "author_affiliation_numbers": "",
                "author_affiliations": "",
                "warnings": warnings_text or "No authors extracted",
            })
        else:
            for author in enriched_authors:
                detail_rows.append({
                    "paper_index": str(paper_index),
                    "pmid": pmid,
                    "pmcid": pmcid,
                    "doi": doi,
                    "source": source,
                    "author_order": str(author.get("order", "")),
                    "author_name": author.get("name", ""),
                    "author_affiliation_numbers": ";".join(str(n) for n in author.get("affiliation_numbers", [])),
                    "author_affiliations": " || ".join(author.get("affiliations", [])),
                    "warnings": warnings_text,
                })

        summary_rows.append({
            "paper_index": str(paper_index),
            "pmid": pmid,
            "pmcid": pmcid,
            "doi": doi,
            "source": source,
            "authors": authors_formatted,
            "affiliations": affiliations_formatted,
            "warnings": warnings_text,
        })

    write_csv(output_path, detail_rows, [
        "paper_index", "pmid", "pmcid", "doi", "source", "author_order", "author_name",
        "author_affiliation_numbers", "author_affiliations", "warnings"
    ])

    summary_path = output_path.with_name(output_path.stem + "_summary.csv")
    write_csv(summary_path, summary_rows, [
        "paper_index", "pmid", "pmcid", "doi", "source", "authors", "affiliations", "warnings"
    ])

    print(f"Saved detail CSV : {output_path}")
    print(f"Saved summary CSV: {summary_path}")


def write_csv(path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    if len(sys.argv) != 3:
        print("使い方:")
        print("  python pmid_pmcid_to_authors_affiliations.py input_papers.csv authors_affiliations.csv")
        print("")
        print("入力CSVは pmid, pmcid, doi, citation のどれかの列を含めてください。")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        print(f"Input not found: {input_path}")
        sys.exit(1)

    process(input_path, output_path)


if __name__ == "__main__":
    main()
