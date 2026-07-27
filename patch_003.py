from pathlib import Path
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch003.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

marker = "        AliasService.warmup()\n"

insert = """
        AliasService.warmup()

        # Lookup cache
        self._representative_cache = {}
        self._product_cache = {}
"""

if marker not in text:
    raise SystemExit("AliasService.warmup() satırı bulunamadı.")

text = text.replace(marker, insert, 1)

FILE.write_text(text, encoding="utf-8")

print("PATCH-003 OK")
print("Backup:", backup)
