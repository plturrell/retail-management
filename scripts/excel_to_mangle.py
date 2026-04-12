#!/usr/bin/env python3
"""
Reads Excel files from an input directory and generates Mangle fact tables
(.mangle files) in an output directory.

Usage:
    python3 scripts/excel_to_mangle.py
    python3 scripts/excel_to_mangle.py --input docs/ --output mangle_facts/
"""

import argparse
import math
import os
import re
import sys

import pandas as pd


def sanitize_name(name: str) -> str:
    """Convert a string to a valid Mangle identifier (lowercase, underscores)."""
    name = str(name).lower()
    # Replace any non-alphanumeric characters with underscores
    name = re.sub(r"[^a-z0-9]+", "_", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")
    return name


def filename_to_prefix(filename: str) -> str:
    """
    Convert an Excel filename to a Mangle relation prefix.

    Naming conventions observed from existing files:
    - 'CATG SKU PLU PROMO Master Data JEWEL v2 (CAG Version).xlsx'
      -> 'catg_sku_plu_promo_master_data_jewel_v2_cag_version'
    - '7. Retail NEC POS Dimensions (1).xlsx'
      -> 'f_7_retail_nec_pos_dimensions_1'
    - '8. Tenant Retail POS Request Forms v2.xlsx'
      -> 'f_8_tenant_retail_pos_request_forms_v2'
    - '8. Tenant Retail POS Request Forms-COMPLETE.xlsx'
      -> 'f_8_tenant_retail_pos_request_forms_complete'
    """
    # Remove the .xlsx extension
    name = os.path.splitext(filename)[0]

    # Check if the filename starts with a digit followed by a period (e.g., "7. ...")
    # These get an "f_" prefix
    match = re.match(r"^(\d+)\.\s*(.*)", name)
    if match:
        number = match.group(1)
        rest = match.group(2)
        prefix = f"f_{number}_"
        return prefix + sanitize_name(rest)
    else:
        return sanitize_name(name)


def sheet_to_suffix(sheet_name: str) -> str:
    """Convert a sheet name to a Mangle relation suffix."""
    return sanitize_name(sheet_name)


def is_descriptor_row(row: pd.Series) -> bool:
    """
    Detect if a row is a type descriptor row (e.g., 'Character(20), M').
    These rows describe column types and should be skipped.
    """
    descriptor_patterns = [
        r"Character\(",
        r"Char\(",
        r"Date\(",
        r"^NOT USE$",
        r"Numeric\(",
        r"Integer\(",
    ]
    pattern = re.compile("|".join(descriptor_patterns), re.IGNORECASE)
    for val in row.values:
        if isinstance(val, str) and pattern.search(val):
            return True
    return False


def get_mangle_type(dtype) -> str:
    """Map pandas dtype to Mangle type string."""
    dtype_str = str(dtype)
    if "int" in dtype_str:
        return "Int64"
    elif "float" in dtype_str:
        return "Float64"
    else:
        return "String"


def format_value(val, mangle_type: str) -> str:
    """
    Format a single value for Mangle output.

    Rules:
    - NaN/None -> "null" (quoted) for String columns, "null" for numeric
    - Integers (including float values that are whole numbers) -> unquoted integer
    - Floats -> unquoted float
    - Strings -> quoted, with internal quotes escaped
    """
    # Handle NaN/None
    if val is None or (isinstance(val, float) and math.isnan(val)):
        if mangle_type == "String":
            return '"null"'
        else:
            return '"null"'

    # Handle numeric values (int or float that is a whole number)
    if isinstance(val, (int,)) and not isinstance(val, bool):
        return str(val)

    if isinstance(val, float):
        if val == val and not math.isinf(val):  # not NaN, not inf
            if val == int(val) and abs(val) < 1e18:
                return str(int(val))
            else:
                return str(val)
        return '"null"'

    # Handle strings
    s = str(val)
    # Check if the string value is numeric
    try:
        num = float(s)
        if num == num and not math.isinf(num):  # valid number
            if num == int(num) and "." not in s and abs(num) < 1e18:
                return str(int(num))
            elif "." not in s and abs(num) < 1e18:
                return str(int(num))
    except (ValueError, OverflowError):
        pass

    # Quote the string value, escaping internal quotes
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    # Replace newlines with spaces (matching existing behavior)
    s = s.replace("\n", " ").replace("\r", " ")
    return f'"{s}"'


def process_sheet(df: pd.DataFrame, relation_name: str) -> str:
    """Process a DataFrame into Mangle format."""
    lines = []

    # Clean column names
    col_names = []
    for i, col in enumerate(df.columns):
        col_str = str(col)
        if col_str.startswith("Unnamed:"):
            col_names.append(f"unnamed_{i}")
        else:
            col_names.append(sanitize_name(col_str))
    df.columns = col_names

    # Skip descriptor rows at the start
    start_idx = 0
    if len(df) > 0 and is_descriptor_row(df.iloc[0]):
        start_idx = 1
    df = df.iloc[start_idx:].reset_index(drop=True)

    # Determine Mangle types for each column based on pandas dtypes
    mangle_types = [get_mangle_type(df[col].dtype) for col in df.columns]

    # Generate DeclDecl header
    lines.append(f"DeclDecl({relation_name},")
    lines.append("  [")
    for i, (col, mtype) in enumerate(zip(df.columns, mangle_types)):
        comma = "," if i < len(df.columns) - 1 else ""
        lines.append(f'    FieldDecl("{col}", "{mtype}"){comma}')
    lines.append("  ]")
    lines.append(").")
    lines.append("")

    # Generate fact rows
    for _, row in df.iterrows():
        values = []
        for col, mtype in zip(df.columns, mangle_types):
            values.append(format_value(row[col], mtype))
        fact_line = f'{relation_name}({", ".join(values)}).'
        lines.append(fact_line)

    return "\n".join(lines) + "\n"


def process_excel_file(filepath: str, output_dir: str) -> list[str]:
    """Process one Excel file and write .mangle files for each sheet."""
    filename = os.path.basename(filepath)
    prefix = filename_to_prefix(filename)

    generated = []

    # Read all sheets
    xl = pd.ExcelFile(filepath, engine="openpyxl")

    for sheet_name in xl.sheet_names:
        suffix = sheet_to_suffix(sheet_name)
        relation_name = f"{prefix}_{suffix}"
        output_filename = f"{relation_name}.mangle"
        output_path = os.path.join(output_dir, output_filename)

        try:
            df = pd.read_excel(xl, sheet_name=sheet_name)
        except Exception as e:
            print(f"  WARNING: Could not read sheet '{sheet_name}': {e}")
            continue

        if df.empty and len(df.columns) == 0:
            print(f"  SKIP: '{sheet_name}' is empty")
            continue

        content = process_sheet(df, relation_name)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        generated.append(output_filename)
        print(f"  -> {output_filename} ({len(df)} rows after filtering)")

    xl.close()
    return generated


def main():
    parser = argparse.ArgumentParser(
        description="Convert Excel files to Mangle fact tables."
    )
    parser.add_argument(
        "--input",
        default="docs/",
        help="Input directory containing Excel files (default: docs/)",
    )
    parser.add_argument(
        "--output",
        default="mangle_facts/",
        help="Output directory for .mangle files (default: mangle_facts/)",
    )
    args = parser.parse_args()

    # Resolve paths relative to the project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    input_dir = os.path.join(project_root, args.input) if not os.path.isabs(args.input) else args.input
    output_dir = os.path.join(project_root, args.output) if not os.path.isabs(args.output) else args.output

    if not os.path.isdir(input_dir):
        print(f"ERROR: Input directory '{input_dir}' does not exist.")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    # Find all .xlsx files
    excel_files = sorted(
        f for f in os.listdir(input_dir)
        if f.endswith(".xlsx") and not f.startswith("~$")
    )

    if not excel_files:
        print(f"No Excel files found in '{input_dir}'.")
        sys.exit(0)

    total_generated = []

    for excel_file in excel_files:
        filepath = os.path.join(input_dir, excel_file)
        print(f"\nProcessing: {excel_file}")
        generated = process_excel_file(filepath, output_dir)
        total_generated.extend(generated)

    print(f"\n{'='*60}")
    print(f"Summary: Generated {len(total_generated)} .mangle files from {len(excel_files)} Excel files.")
    for f in total_generated:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
