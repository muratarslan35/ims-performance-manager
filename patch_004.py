from pathlib import Path
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch004.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

if "logger.info(\"FACT Builder başlatılıyor\")" in text:
    print("PATCH-004 daha önce uygulanmış.")
    raise SystemExit(0)

old = """        self.statistics[

            "processed_sheet"

        ] += 1"""

new = """        self.statistics[

            "processed_sheet"

        ] += 1

        logger.info(

            "FACT Builder başlatılıyor (%s)",

            sheet_type

        )

        try:

            IMSFactBuilderService().build(

                upload_id=self.upload.id,

                year=year,

                month=month,

                sheet_type=sheet_type

            )

        except Exception:

            logger.exception(

                "FACT Builder hatası"

            )

            raise

        logger.info(

            "FACT Builder tamamlandı (%s)",

            sheet_type

        )"""

if old not in text:
    raise SystemExit("process_sheet() sonu bulunamadı.")

text = text.replace(old, new, 1)

FILE.write_text(text, encoding="utf-8")

print("PATCH-004 OK")
print("Backup:", backup)
