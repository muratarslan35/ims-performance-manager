from pathlib import Path
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch007.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old = """    def flush_raw_buffer(

        self

    ):

        if not self._raw_buffer:

            return

        for record in self._raw_buffer:

            db.session.add(

                record

            )

        logger.info(

            "RAW buffer flush: %s kayıt",

            len(

                self._raw_buffer

            )

        )

        self._raw_buffer.clear()
"""

new = """    def flush_raw_buffer(

        self

    ):

        if not self._raw_buffer:

            return

        try:

            db.session.bulk_save_objects(

                self._raw_buffer

            )

            logger.info(

                "RAW buffer bulk insert: %s kayıt",

                len(

                    self._raw_buffer

                )

            )

            self.statistics.setdefault(

                "bulk_batches",

                0

            )

            self.statistics.setdefault(

                "bulk_records",

                0

            )

            self.statistics["bulk_batches"] += 1

            self.statistics["bulk_records"] += len(

                self._raw_buffer

            )

            self._raw_buffer.clear()

        except Exception:

            db.session.rollback()

            logger.exception(

                "RAW bulk insert hatası"

            )

            raise
"""

if old not in text:
    raise SystemExit("flush_raw_buffer() bloğu bulunamadı.")

text = text.replace(old, new, 1)

FILE.write_text(text, encoding="utf-8")

print("PATCH-007 OK")
print("Backup:", backup)
