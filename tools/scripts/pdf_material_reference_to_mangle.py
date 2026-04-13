#!/usr/bin/env python3
"""
Convert a scanned stone/material reference PDF into normalized JSON and Mangle facts.

This is intended for offline/local-first use:
  - render PDF pages with pdftoppm
  - OCR each page with pytesseract
  - extract a material/stone master dataset
  - optionally link the extracted materials to existing pos_item material text

Outputs:
  - JSON seed file for later database import
  - Mangle fact file for immediate rule/query use

Example:
  python3 tools/scripts/pdf_material_reference_to_mangle.py \
    --input "docs/Adobe Scan 12 Apr 2026.pdf" \
    --output-json "data/ocr_outputs/material_reference_adobe_scan_12_apr_2026.json" \
    --output-mangle "data/mangle_facts/material_reference.mangle" \
    --pos-items "data/mangle_facts/pos_orders.mangle"
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

from PIL import Image, ImageOps
import pytesseract


NOISE_LINES = {
    "ee",
    "oe",
    "eae",
    "©",
    "@",
    "0",
}

STOPWORDS = {
    "and",
    "in",
    "of",
    "the",
    "with",
    "for",
    "only",
}

GENERIC_LINK_ALIASES = {
    "stone",
    "crystal",
    "gem",
    "rock",
    "mineral",
    "marble",
    "quartz",
    "tourmaline",
    "agate",
    "jade",
    "mica",
    "amber",
    "sapphire",
    "ruby",
}

PAGE_TITLE_OVERRIDES = {
    1: "Agate",
    6: "Angelite",
    11: "Aventurine",
    21: "Copper Rutilated Quartz",
    23: "Dragon Blood Stone",
    24: "Eagle Eye",
    25: "Fluorite",
    29: "Green Mica",
    32: "Lapis Lazuli",
    34: "Imperial Diopside (Siberian Emerald)",
    35: "Jade",
    39: "Labradorite",
    40: "Lapis Lazuli",
    41: "Larimar",
    43: "Morganite",
    44: "Moonstone",
    45: "Meteorite",
    46: "Onyx",
    48: "Obsidian",
    49: "Pyrite",
    51: "Petersite",
    52: "Rhodochrosite",
    53: "Rose Quartz",
    54: "Ruby",
    56: "Rhodonite",
    63: "Turquoise",
    65: "Topaz",
}

TITLE_CORRECTIONS = {
    "ame": "Agate",
    "angelite": "Angelite",
    "aventurine": "Aventurine",
    "imperia diopside siberian emerald": "Imperial Diopside (Siberian Emerald)",
    "lapislezuli": "Lapis Lazuli",
    "lapis lezuli": "Lapis Lazuli",
    "lapis lazull": "Lapis Lazuli",
    "lanmar": "Larimar",
    "reorganite": "Morganite",
    "meonstone": "Moonstone",
    "peterside": "Petersite",
    "rhocochrosite": "Rhodochrosite",
    "rhoceriite": "Rhodonite",
    "ose quartz": "Rose Quartz",
    "tope": "Topaz",
}

FIELD_VALUE_CORRECTIONS = {
    "troat": "Throat",
    "third eye": "Third Eye",
    "solar plexus": "Solar Plexus",
    "sacral chakra": "Sacral Chakra",
}

FIELD_VALUE_PREFIXES = {
    "all chakras": "All Chakras",
    "third eye": "Third Eye",
    "solar plexus": "Solar Plexus",
    "sacral chakra": "Sacral Chakra",
    "heart": "Heart",
    "throat": "Throat",
    "brow": "Brow",
    "root": "Root",
    "crown": "Crown",
}


@dataclass
class MaterialEntry:
    material_key: str
    display_name: str
    page_no: int
    summary: str
    keywords: list[str]
    chakras: list[str]
    origins: list[str]
    aliases: list[str]
    source_doc: str
    raw_text: str


def normalize_space(text: str) -> str:
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fix_title(text: str) -> str:
    text = normalize_space(text)
    text = re.sub(r"\b([A-Z][a-z]{1,3}) ([a-z]{3,})\b", r"\1\2", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\(\s+", "(", text)
    return text


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def normalize_lookup_key(text: str) -> str:
    text = normalize_space(text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def normalize_field_value(value: str) -> str:
    value = normalize_space(value).strip(" |_-.,:;")
    key = normalize_lookup_key(value)
    if key in FIELD_VALUE_CORRECTIONS:
        return FIELD_VALUE_CORRECTIONS[key]
    for prefix, canonical in FIELD_VALUE_PREFIXES.items():
        if key.startswith(prefix):
            return canonical
    if value.upper() in {"USA", "US"}:
        return value.upper()
    if value.islower():
        return value.title()
    return value


def parse_list_field(value: str) -> list[str]:
    cleaned = normalize_space(value)
    cleaned = cleaned.replace("|", ",")
    cleaned = re.sub(r"\b(?:source|chakra)\b\s*:?", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\band\b", ",", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*&\s*", ",", cleaned)
    cleaned = cleaned.replace("/", ",")
    cleaned = re.sub(r"[©{}]+", " ", cleaned)
    parts = [normalize_space(part) for part in cleaned.split(",")]
    values: list[str] = []
    for part in parts:
        part = re.sub(r"\b\d+\b", " ", part)
        part = normalize_field_value(part)
        if not part or not re.search(r"[A-Za-z]", part):
            continue
        if part not in values:
            values.append(part)
    return values


def clean_title_candidate(text: str) -> str:
    text = normalize_space(text)
    text = text.replace("©", " ").replace("|", " ")
    text = re.sub(r"\.\.+$", "", text)
    text = re.sub(r"^[^A-Za-z0-9(]+", "", text)
    text = re.sub(r"[^A-Za-z0-9)]+$", "", text)
    text = fix_title(text)
    return text.strip(" -_~|.,:;")


def title_score(text: str) -> int:
    if not text:
        return -100
    score = 0
    words = text.split()
    letters = re.sub(r"[^A-Za-z]", "", text)
    lower = text.lower()
    if 1 <= len(words) <= 5:
        score += 4
    if len(text) <= 40:
        score += 2
    if letters and text[0].isupper():
        score += 2
    if re.search(r"\b(?:chakra|source)\b", lower):
        score -= 6
    if re.search(r"[.!?]", text):
        score -= 4
    if len(words) > 7:
        score -= 3
    if sum(word[:1].isupper() for word in words) >= max(1, len(words) - 1):
        score += 2
    return score


def select_title(lines: list[str], title_hint: str) -> str:
    candidates = [clean_title_candidate(title_hint)]
    candidates.extend(clean_title_candidate(line) for line in lines[:4])
    best = max(candidates, key=title_score)
    return best


def correct_title(title: str, page_no: int) -> str:
    if page_no in PAGE_TITLE_OVERRIDES:
        return PAGE_TITLE_OVERRIDES[page_no]

    cleaned = clean_title_candidate(title)
    key = normalize_lookup_key(cleaned)
    if key in TITLE_CORRECTIONS:
        return TITLE_CORRECTIONS[key]
    return cleaned


def same_title(left: str, right: str) -> bool:
    return slugify(left) == slugify(right)


def strip_title_prefix(text: str, title: str) -> str:
    stripped = normalize_space(text)
    if not stripped or not title:
        return stripped

    title_key = slugify(title)
    tokens = stripped.split()
    for token_count in range(min(5, len(tokens)), 0, -1):
        candidate = " ".join(tokens[:token_count])
        if slugify(candidate) == title_key:
            return normalize_space(" ".join(tokens[token_count:]))
    return stripped


def strip_metadata_text(text: str) -> str:
    text = re.sub(r"\bchakra\s*:.*?(?=\bsource\b\s*:|$)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsource\s*:.*$", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[|©_]+", " ", text)
    return normalize_space(text)


def build_aliases(title: str) -> list[str]:
    aliases: list[str] = []
    full = normalize_space(title)
    if full:
        aliases.append(full)

    without_parens = normalize_space(re.sub(r"\(.*?\)", "", full))
    if without_parens and without_parens not in aliases:
        aliases.append(without_parens)

    for inner in re.findall(r"\((.*?)\)", full):
        for token in re.split(r"[,/]| in ", inner):
            token = normalize_space(token)
            if token and token.lower() not in STOPWORDS and token not in aliases:
                aliases.append(token)

    return aliases


def is_useful_alias(alias: str, title: str) -> bool:
    alias = clean_title_candidate(alias)
    if not alias or same_title(alias, title) or is_keyword_line(alias):
        return False
    words = alias.split()
    if not 1 <= len(words) <= 4:
        return False
    if any(len(re.sub(r"[^A-Za-z]", "", word)) <= 1 for word in words[1:]):
        return False
    if re.search(r"""['"]""", alias):
        return False
    return title_score(alias) >= 2


def extract_keywords(line: str) -> list[str]:
    candidate = normalize_space(line)
    candidate = candidate.replace("©", "|").replace("@", "|").replace("?", "")
    groups = re.findall(r"[A-Z][A-Z &'/-]{2,}", candidate)
    keywords = []
    for group in groups:
        keyword = normalize_space(group.replace("|", " "))
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return keywords


def is_keyword_line(line: str) -> bool:
    stripped = normalize_space(line)
    if not stripped:
        return False
    keywords = extract_keywords(stripped)
    if len(keywords) >= 2:
        return True
    letters = re.sub(r"[^A-Za-z]", "", stripped)
    if not letters:
        return False
    upper_ratio = sum(ch.isupper() for ch in letters) / len(letters)
    return upper_ratio > 0.8 and len(stripped) <= 60


def clean_ocr_lines(raw_text: str) -> list[str]:
    lines = []
    for raw_line in raw_text.splitlines():
        line = normalize_space(raw_line)
        if not line or line.lower() in NOISE_LINES:
            continue
        lines.append(line)
    return lines


def parse_page(
    raw_text: str,
    page_no: int,
    source_doc: str,
    title_hint: str,
) -> MaterialEntry | None:
    lines = clean_ocr_lines(raw_text)
    if not lines and not title_hint:
        return None

    raw_title = select_title(lines, title_hint)
    title = correct_title(raw_title, page_no)
    flat_text = normalize_space(raw_text)
    keywords: list[str] = []
    chakras: list[str] = []
    origins: list[str] = []
    body_lines: list[str] = []

    chakra_match = re.search(
        r"\bchakra\s*:\s*(.*?)(?=\bsource\b\s*:|$)",
        flat_text,
        flags=re.IGNORECASE,
    )
    if chakra_match:
        chakras = parse_list_field(chakra_match.group(1))

    source_match = re.search(r"\bsource\s*:\s*(.*)$", flat_text, flags=re.IGNORECASE)
    if source_match:
        origins = parse_list_field(source_match.group(1))

    for line in lines:
        low = line.lower()
        if same_title(line, title) or same_title(line, raw_title):
            continue
        if re.search(r"\b(?:chakra|source)\s*:", line, flags=re.IGNORECASE):
            continue
        if is_keyword_line(line):
            for keyword in extract_keywords(line):
                if keyword not in keywords:
                    keywords.append(keyword)
            continue
        body_line = strip_title_prefix(line, title)
        body_line = strip_title_prefix(body_line, raw_title)
        body_line = strip_metadata_text(body_line)
        if body_line:
            body_lines.append(body_line)

    summary = strip_metadata_text(" ".join(body_lines))
    material_key = slugify(title)
    aliases = build_aliases(title)
    cleaned_raw_title = clean_title_candidate(raw_title)
    if is_useful_alias(cleaned_raw_title, title):
        if cleaned_raw_title not in aliases:
            aliases.append(cleaned_raw_title)

    return MaterialEntry(
        material_key=material_key,
        display_name=title,
        page_no=page_no,
        summary=summary,
        keywords=keywords,
        chakras=chakras,
        origins=origins,
        aliases=aliases,
        source_doc=source_doc,
        raw_text=normalize_space(raw_text),
    )


def render_pdf_pages(pdf_path: Path, temp_dir: Path) -> list[Path]:
    output_prefix = temp_dir / "material_page"
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            "250",
            "-png",
            str(pdf_path),
            str(output_prefix),
        ],
        check=True,
    )
    return sorted(temp_dir.glob("material_page-*.png"))


def ocr_page(image_path: Path) -> str:
    image = Image.open(image_path)
    return pytesseract.image_to_string(image, config="--psm 6")


def ocr_title(image_path: Path) -> str:
    image = Image.open(image_path)
    width, height = image.size
    crop = image.crop((0, 0, width, int(height * 0.2))).convert("L")
    crop = ImageOps.autocontrast(crop)
    crop = crop.point(lambda pixel: 255 if pixel > 175 else 0)
    return pytesseract.image_to_string(crop, config="--psm 7")


def read_pos_item_materials(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []

    results: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("pos_item("):
            continue
        values = re.findall(r'"((?:\\"|[^"])*)"', line)
        if len(values) < 4:
            continue
        code = values[2].replace('\\"', '"')
        material_text = values[3].replace('\\"', '"')
        if material_text:
            results.append((code, material_text))
    return results


def build_product_material_hints(
    entries: list[MaterialEntry],
    pos_items: list[tuple[str, str]],
) -> list[dict]:
    hints: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for code, material_text in pos_items:
        material_text_lc = material_text.lower()
        for entry in entries:
            matched_alias = None
            for alias in entry.aliases:
                alias_lc = alias.lower()
                if len(alias_lc) < 4 or alias_lc in GENERIC_LINK_ALIASES:
                    continue
                pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias_lc)}(?![a-z0-9])")
                if pattern.search(material_text_lc):
                    matched_alias = alias
                    break
            if matched_alias is None:
                continue

            key = (code, entry.material_key, material_text)
            if key in seen:
                continue
            seen.add(key)
            hints.append(
                {
                    "code": code,
                    "material_key": entry.material_key,
                    "matched_name": matched_alias,
                    "source_text": material_text,
                }
            )
    return hints


def dedupe_entries(entries: list[MaterialEntry]) -> tuple[list[MaterialEntry], list[str]]:
    merged: dict[str, MaterialEntry] = {}
    duplicates: list[str] = []

    for entry in entries:
        existing = merged.get(entry.material_key)
        if existing is None:
            merged[entry.material_key] = entry
            continue

        duplicates.append(f"{entry.display_name} (page {entry.page_no})")
        if len(entry.summary) > len(existing.summary):
            existing.summary = entry.summary
        for field_name in ("keywords", "chakras", "origins", "aliases"):
            existing_values = getattr(existing, field_name)
            for value in getattr(entry, field_name):
                if value not in existing_values:
                    existing_values.append(value)

    return list(merged.values()), duplicates


def mangle_str(value: str) -> str:
    return '"' + value.replace('"', '\\"').replace("\n", " ").strip() + '"'


def write_mangle(
    output_path: Path,
    entries: list[MaterialEntry],
    hints: list[dict],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("# Auto-generated material reference facts from scanned PDF\n")
        handle.write("# Schema:\n")
        handle.write("#   material_reference(material_key, display_name, source_doc, page_no, summary).\n")
        handle.write("#   material_keyword(material_key, keyword).\n")
        handle.write("#   material_chakra(material_key, chakra).\n")
        handle.write("#   material_origin(material_key, origin).\n")
        handle.write("#   material_alias(material_key, alias).\n")
        handle.write("#   product_material_hint(code, material_key, matched_name, source_text).\n\n")

        handle.write(
            'DeclDecl(material_reference, [FieldDecl("material_key", "String"), '
            'FieldDecl("display_name", "String"), FieldDecl("source_doc", "String"), '
            'FieldDecl("page_no", "Int64"), FieldDecl("summary", "String")]).\n'
        )
        handle.write(
            'DeclDecl(material_keyword, [FieldDecl("material_key", "String"), '
            'FieldDecl("keyword", "String")]).\n'
        )
        handle.write(
            'DeclDecl(material_chakra, [FieldDecl("material_key", "String"), '
            'FieldDecl("chakra", "String")]).\n'
        )
        handle.write(
            'DeclDecl(material_origin, [FieldDecl("material_key", "String"), '
            'FieldDecl("origin", "String")]).\n'
        )
        handle.write(
            'DeclDecl(material_alias, [FieldDecl("material_key", "String"), '
            'FieldDecl("alias", "String")]).\n'
        )
        handle.write(
            'DeclDecl(product_material_hint, [FieldDecl("code", "String"), '
            'FieldDecl("material_key", "String"), FieldDecl("matched_name", "String"), '
            'FieldDecl("source_text", "String")]).\n\n'
        )

        for entry in entries:
            handle.write(
                f"material_reference({mangle_str(entry.material_key)}, "
                f"{mangle_str(entry.display_name)}, {mangle_str(entry.source_doc)}, "
                f"{entry.page_no}, {mangle_str(entry.summary)}).\n"
            )
            for keyword in entry.keywords:
                handle.write(
                    f"material_keyword({mangle_str(entry.material_key)}, "
                    f"{mangle_str(keyword)}).\n"
                )
            for chakra in entry.chakras:
                handle.write(
                    f"material_chakra({mangle_str(entry.material_key)}, "
                    f"{mangle_str(chakra)}).\n"
                )
            for origin in entry.origins:
                handle.write(
                    f"material_origin({mangle_str(entry.material_key)}, "
                    f"{mangle_str(origin)}).\n"
                )
            for alias in entry.aliases:
                handle.write(
                    f"material_alias({mangle_str(entry.material_key)}, "
                    f"{mangle_str(alias)}).\n"
                )
            handle.write("\n")

        for hint in hints:
            handle.write(
                f"product_material_hint({mangle_str(hint['code'])}, "
                f"{mangle_str(hint['material_key'])}, "
                f"{mangle_str(hint['matched_name'])}, "
                f"{mangle_str(hint['source_text'])}).\n"
            )


def write_json(output_path: Path, entries: list[MaterialEntry], hints: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "materials": [asdict(entry) for entry in entries],
        "product_material_hints": hints,
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input scanned PDF")
    parser.add_argument(
        "--output-json",
        default="data/ocr_outputs/material_reference.json",
        help="Normalized JSON output",
    )
    parser.add_argument(
        "--output-mangle",
        default="data/mangle_facts/material_reference.mangle",
        help="Mangle facts output",
    )
    parser.add_argument(
        "--pos-items",
        default="data/mangle_facts/pos_orders.mangle",
        help="Optional Mangle file containing pos_item facts for hint linking",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]

    def _repo_path(p: str | Path) -> Path:
        path = Path(p)
        return path.resolve() if path.is_absolute() else (repo_root / path).resolve()

    pdf_path = Path(args.input).resolve()
    json_path = _repo_path(args.output_json)
    mangle_path = _repo_path(args.output_mangle)
    pos_items_path = _repo_path(args.pos_items)

    if not pdf_path.exists():
        raise SystemExit(f"Input PDF not found: {pdf_path}")

    with tempfile.TemporaryDirectory(prefix="material_pdf_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        page_images = render_pdf_pages(pdf_path, temp_dir)
        entries: list[MaterialEntry] = []

        for page_no, image_path in enumerate(page_images, start=1):
            raw_text = ocr_page(image_path)
            title_hint = ocr_title(image_path)
            entry = parse_page(raw_text, page_no, pdf_path.name, title_hint)
            if entry is not None and entry.display_name:
                entries.append(entry)

    entries, duplicates = dedupe_entries(entries)
    pos_items = read_pos_item_materials(pos_items_path)
    hints = build_product_material_hints(entries, pos_items)

    write_json(json_path, entries, hints)
    write_mangle(mangle_path, entries, hints)

    print(f"Extracted {len(entries)} material reference page(s)")
    if duplicates:
        print(f"Collapsed duplicates: {', '.join(duplicates)}")
    print(f"Product material hints: {len(hints)}")
    print(f"JSON   -> {json_path}")
    print(f"Mangle -> {mangle_path}")


if __name__ == "__main__":
    main()
