from pathlib import Path
import re
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch002.bak")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

pattern = re.compile(
    r'def load_workbook\(\s*self\s*\)\s*:\s*.*?return self\.workbook',
    re.S
)

replacement = '''
def load_workbook(

        self

    ):

        logger.info("IMS workbook yükleniyor: %s", self.file_path)

        if not os.path.exists(self.file_path):

            raise FileNotFoundError(

                f"Dosya bulunamadı: {self.file_path}"

            )

        try:

            self.workbook = pd.read_excel(

                self.file_path,

                sheet_name=None,

                header=None

            )

        except Exception:

            logger.exception(

                "Workbook okunamadı."

            )

            raise

        self.statistics["sheet_count"] = len(

            self.workbook

        )

        logger.info(

            "Workbook yüklendi (%s sheet)",

            self.statistics["sheet_count"]

        )

        return self.workbook
'''

new_text, count = pattern.subn(replacement, text, count=1)

if count != 1:
    raise SystemExit("load_workbook() bulunamadı veya beklenen formatta değil.")

FILE.write_text(new_text, encoding="utf-8")

print("PATCH-002 OK")
print("Backup:", backup)
