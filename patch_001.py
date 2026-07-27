from pathlib import Path
import re
import shutil

FILE = Path("app/services/ims_import_service.py")

if not FILE.exists():
    raise SystemExit("ims_import_service.py bulunamadı.")

backup = FILE.with_suffix(".patch001.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

# --------------------------------------------------
# logging import
# --------------------------------------------------

if "import logging" not in text:

    m = re.search(r"^import .*?$", text, re.M)

    if m:
        pos = m.end()
        text = text[:pos] + "\nimport logging" + text[pos:]

# --------------------------------------------------
# logger
# --------------------------------------------------

if "logger = logging.getLogger(__name__)" not in text:

    m = re.search(
        r"from app\.services\.alias_service import AliasService.*?\n",
        text,
    )

    if m:
        pos = m.end()

        text = (
            text[:pos]
            + "\nlogger = logging.getLogger(__name__)\n"
            + text[pos:]
        )

# --------------------------------------------------
# VERSION
# --------------------------------------------------

if 'SERVICE_VERSION = "3.0.0"' not in text:

    m = re.search(
        r"class\s+IMSImportService\s*:",
        text,
    )

    if m:

        pos = m.end()

        text = (
            text[:pos]
            + """

    SERVICE_VERSION = "3.0.0"

"""
            + text[pos:]
        )

# --------------------------------------------------

FILE.write_text(text, encoding="utf-8")

print()
print("=" * 60)
print("PATCH-001 OK")
print("Backup :", backup)
print("=" * 60)
