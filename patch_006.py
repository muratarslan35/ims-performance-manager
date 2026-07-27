from pathlib import Path
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch006.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old = '''        self.flush_raw_buffer()

        logger.info(

            "FACT Builder başlatılıyor (%s)",

            sheet_type

        )

        try:

            IMSFactBuilderService.build(

                self.upload.id

            )

        except Exception:

            logger.exception(

                "FACT Builder hatası"

            )

            raise

        logger.info(

            "FACT Builder tamamlandı (%s)",

            sheet_type

        )'''

new = '''        self.flush_raw_buffer()'''

if old not in text:
    raise SystemExit("PATCH-004 bloğu bulunamadı.")

text = text.replace(old, new, 1)

FILE.write_text(text, encoding="utf-8")

print("PATCH-006 OK")
print("Backup:", backup)
