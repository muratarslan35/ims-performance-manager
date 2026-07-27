from pathlib import Path
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch004fix.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old = """            IMSFactBuilderService().build(

                upload_id=self.upload.id,

                year=year,

                month=month,

                sheet_type=sheet_type

            )"""

new = """            IMSFactBuilderService.build(

                self.upload.id

            )"""

if old not in text:
    raise SystemExit("PATCH-004 çağrısı bulunamadı.")

text = text.replace(old, new, 1)

FILE.write_text(text, encoding="utf-8")

print("PATCH-004.1 OK")
print("Backup:", backup)
