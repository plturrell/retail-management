"""NEC Jewel POS field-length / enum limits.

Source: the NEC Jewel master-data integration spec ("Catalog import — fixed
columns" PDF, vendor-supplied). Changing any of these values without a
matching vendor confirmation will silently truncate or drop fields when the
file is loaded into the POS, so they live here flagged as *contractual*.

Used by :mod:`app.services.nec_jewel_preview` and the catalog publish path.
"""

#: SKU code is the 16-char identifier the POS uses internally. Truncated past
#: this limit by Jewel without warning.
MAX_SKU_CODE: int = 16

#: Short display description shown on receipts. Anything beyond is silently
#: cropped on the POS terminal display.
MAX_SKU_DESC: int = 60

#: PLU code (long-form product look-up). Matches the column width Jewel
#: tolerates in catalog imports.
MAX_PLU_CODE: int = 80

#: Brand name field. Jewel rejects rows where this column overflows.
MAX_BRAND: int = 20

#: Permitted age-group enum values. Anything outside the set fails validation.
VALID_AGE_GROUPS: frozenset[str] = frozenset({"ADULT", "CHILD<12", "ALL"})

#: Permitted gender enum values (empty string allowed for "unspecified").
VALID_GENDERS: frozenset[str] = frozenset({"", "MALE", "FEMALE", "UNISEX"})
