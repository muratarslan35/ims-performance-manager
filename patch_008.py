from pathlib import Path
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch008.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old = """    def commit(

        self

    ):

        try:

            db.session.commit()

        except SQLAlchemyError as exc:

            db.session.rollback()

            raise Exception(

                str(

                    exc
                )

            )
"""

new = """    def commit(

        self

    ):

        started = time.time()

        try:

            db.session.commit()

            logger.info(

                "Commit başarılı (%.3f sn)",

                time.time() - started

            )

        except SQLAlchemyError as exc:

            db.session.rollback()

            logger.exception(

                "Commit başarısız"

            )

            self.errors.append(

                str(exc)

            )

            raise
"""

if old not in text:
    raise SystemExit("commit() bloğu bulunamadı.")

text = text.replace(old, new, 1)

FILE.write_text(text, encoding="utf-8")

print("PATCH-008 OK")
print("Backup:", backup)
