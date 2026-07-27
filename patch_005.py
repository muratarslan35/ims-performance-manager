from pathlib import Path
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch005.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

# --------------------------------------------------
# __init__ içerisine raw buffer ekle
# --------------------------------------------------

marker = '        self._product_cache = {}\n'

insert = '''        self._product_cache = {}

        self._raw_buffer = []

        self._raw_buffer_limit = 1000
'''

if marker not in text:
    raise SystemExit("_product_cache bulunamadı.")

text = text.replace(marker, insert, 1)

# --------------------------------------------------
# create_raw_record db.session.add -> buffer
# --------------------------------------------------

old = '''        db.session.add(

            raw

        )

        self.statistics[

            "raw_records"

        ] += 1

        return raw'''

new = '''        self._raw_buffer.append(

            raw

        )

        if len(

            self._raw_buffer

        ) >= self._raw_buffer_limit:

            self.flush_raw_buffer()

        self.statistics[

            "raw_records"

        ] += 1

        return raw'''

if old not in text:
    raise SystemExit("create_raw_record bloğu bulunamadı.")

text = text.replace(old, new, 1)

# --------------------------------------------------
# flush_raw_buffer metodu
# --------------------------------------------------

if "def flush_raw_buffer(" not in text:

    marker = '''

    def process_sheet(
'''

    flush_method = '''

    def flush_raw_buffer(

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

'''

    if marker not in text:
        raise SystemExit("process_sheet bulunamadı.")

    text = text.replace(marker, flush_method + marker, 1)

# --------------------------------------------------
# process_sheet sonunda flush
# --------------------------------------------------

old = '''        logger.info(

            "FACT Builder başlatılıyor (%s)",'''

new = '''        self.flush_raw_buffer()

        logger.info(

            "FACT Builder başlatılıyor (%s)",'''

if old not in text:
    raise SystemExit("FACT Builder başlangıcı bulunamadı.")

text = text.replace(old, new, 1)

FILE.write_text(text, encoding="utf-8")

print("PATCH-005 OK")
print("Backup:", backup)
