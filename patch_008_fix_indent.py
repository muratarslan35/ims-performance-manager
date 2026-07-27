from pathlib import Path
import shutil

FILE = Path("app/services/ims_import_service.py")

backup = FILE.with_suffix(".patch008indent.bak")
shutil.copy2(FILE, backup)

lines = FILE.read_text(encoding="utf-8").splitlines()

start = None
end = None

for i, line in enumerate(lines):
    if line.startswith("def load_workbook("):
        start = i
        continue

    if start is not None and line.startswith("    def commit("):
        end = i
        break

if start is None or end is None:
    raise SystemExit("load_workbook bloğu bulunamadı.")

for i in range(start, end):
    lines[i] = "    " + lines[i]

FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

print("PATCH-008.1 OK")
print("Backup:", backup)
