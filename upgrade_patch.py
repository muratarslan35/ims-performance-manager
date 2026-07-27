from pathlib import Path
import re
import shutil

FILE = Path("app/services/ims_import_service.py")

if not FILE.exists():
    raise SystemExit(f"Dosya bulunamadı: {FILE}")

backup = FILE.with_suffix(".py.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

def replace_once(pattern, replacement, flags=re.S):
    global text
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"Patch uygulanamadı.\nPattern:\n{pattern}")
    text = new_text

def insert_after(anchor, block):
    global text
    pos = text.find(anchor)
    if pos == -1:
        raise SystemExit(f"Anchor bulunamadı:\n{anchor}")
    pos += len(anchor)
    text = text[:pos] + block + text[pos:]

#
# IMPORTLAR
#

if "import logging" not in text:
    insert_after(
        "import json\n",
        "import logging\n"
    )

if "from collections import defaultdict" not in text:
    insert_after(
        "import time\n",
        "from collections import defaultdict\n"
    )

#
# LOGGER
#

if "logger = logging.getLogger(__name__)" not in text:
    insert_after(
        "from app.services.alias_service import AliasService\n",
        "\nlogger = logging.getLogger(__name__)\n"
    )

FILE.write_text(text, encoding="utf-8")

print("="*60)
print("PATCH-001 BAŞARILI")
print("Yedek :", backup)
print("Dosya :", FILE)
print("="*60)
