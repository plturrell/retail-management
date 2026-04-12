import os
import pandas as pd
import math
import re

DOCS_DIR = "/Users/user/Documents/retailmanagement/docs"
OUTPUT_DIR = "/Users/user/Documents/retailmanagement/mangle_facts"

def sanitize_name(name):
    """Sanitize string to be used as a valid Mangle relation name."""
    # Remove non-alphanumeric characters and replace with underscores
    name = re.sub(r'[^a-zA-Z0-9]', '_', str(name))
    # Remove consecutive underscores
    name = re.sub(r'_+', '_', name)
    # Strip leading/trailing underscores
    name = name.strip('_')
    if not name:
        name = "unknown"
    # Mangle relations usually lowercase
    name = name.lower()
    # If starts with a digit, prefix with `f_`
    if name[0].isdigit():
        name = "f_" + name
    return name

def sanitize_value(val):
    """Sanitize value to be used as a valid Mangle fact argument."""
    if pd.isna(val):
        return '"null"'
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        # If it's a float that is actually an integer, print as int
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        # If it's NaN or Infinity
        if isinstance(val, float) and math.isnan(val):
            return '"null"'
        return str(val)
    if isinstance(val, str):
        # Escape quotes
        val = val.replace('"', '\\"')
        # Replace newlines
        val = val.replace('\n', ' ')
        return f'"{val}"'
    return f'"{str(val)}"'

def is_type_hint_row(row):
    """Check if the row consists of type hints like 'Character(20), M'."""
    for val in row:
        val_str = str(val).lower()
        if "character(" in val_str or "numeric(" in val_str or "varchar" in val_str:
            return True
    return False

def is_empty_row(row):
    """Check if an entire row is empty/NaN."""
    return all(pd.isna(val) or str(val).strip() == "" for val in row)

def is_legend_row(row):
    """Check if a row looks like the start of a legend/footer."""
    if not pd.isna(row.iloc[0]):
        val_str = str(row.iloc[0]).strip().lower()
        if val_str in ["description:", "legend", "tenant's information", "note:"]:
            return True
        if "ilustration" in val_str or "illustration" in val_str:
            return True
    return False

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    for filename in os.listdir(DOCS_DIR):
        if not filename.endswith('.xlsx') or filename.startswith('~'):
            continue
        
        filepath = os.path.join(DOCS_DIR, filename)
        print(f"Processing {filename}...")
        
        try:
            # Read all sheets
            excel_data = pd.read_excel(filepath, sheet_name=None)
            
            # Base table name from filename
            base_name = os.path.splitext(filename)[0]
            
            for sheet_name, df in excel_data.items():
                if df.empty:
                    continue
                    
                table_name = sanitize_name(f"{base_name}_{sheet_name}")
                mangle_file = os.path.join(OUTPUT_DIR, f"{table_name}.mangle")
                
                print(f"  -> Writing sheet '{sheet_name}' to {mangle_file}")
                
                with open(mangle_file, 'w') as f:
                    columns = df.columns.tolist()
                    sanitized_cols = [sanitize_name(c) for c in columns]
                    
                    # Generate DeclDecl schema based on pandas dtypes
                    field_decls = []
                    for col_name, dtype in zip(sanitized_cols, df.dtypes):
                        if pd.api.types.is_integer_dtype(dtype):
                            mangle_type = "Int64"
                        elif pd.api.types.is_float_dtype(dtype):
                            mangle_type = "Float64"
                        elif pd.api.types.is_bool_dtype(dtype):
                            mangle_type = "Bool"
                        else:
                            mangle_type = "String"
                        field_decls.append(f'FieldDecl("{col_name}", "{mangle_type}")')
                    
                    f.write(f"DeclDecl({table_name},\n  [\n")
                    f.write(",\n".join([f"    {fd}" for fd in field_decls]))
                    f.write("\n  ]\n).\n\n")
                    
                    for index, row in df.iterrows():
                        # Stop if we hit an empty row or a legend row
                        if is_empty_row(row) or is_legend_row(row):
                            break
                            
                        # Skip if it is a type hint row
                        if index == 0 and is_type_hint_row(row):
                            continue
                            
                        args = [sanitize_value(val) for val in row]
                        f.write(f"{table_name}({', '.join(args)}).\n")
                        
        except Exception as e:
            print(f"Error processing {filename}: {e}")

if __name__ == "__main__":
    main()
