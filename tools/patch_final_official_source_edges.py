from pathlib import Path

# Official aggregate actuals must work even in narrow/single-product workbooks.
path = Path("app/services/official_aggregate_service.py")
text = path.read_text()
old = '''            if "TRAVAZOL" in " ".join(_norm(value) for value in frame.iloc[index])
            and "MONUROL" in " ".join(_norm(value) for value in frame.iloc[index])
'''
new = '''            if "TRAVAZOL" in " ".join(_norm(value) for value in frame.iloc[index])
'''
if old not in text:
    raise SystemExit("official header anchor not found")
path.write_text(text.replace(old, new, 1))

# Vacant/cadre rows are real target recipients and exact unit targets must not be rounded.
path = Path("app/services/target_import_service.py")
text = path.read_text()
text = text.replace('from app.models import (\n    Target,\n)', 'from app.models import (\n    Representative,\n    Target,\n)', 1)
old = '''        if normalized not in self._representative_match_cache:
            res = AliasService.find_representative(representative_name)
            self._representative_match_cache[normalized] = res
'''
new = '''        if normalized not in self._representative_match_cache:
            res = AliasService.find_representative(representative_name)
            if not res["matched"] and any(token in {"BOS", "KADRO"} for token in normalized.split()):
                matches = [rep for rep in Representative.query.all() if AliasService.normalize(rep.rep_name) == normalized]
                if len(matches) == 1:
                    res = {"matched": True, "object": matches[0], "method": "VACANCY_EXACT"}
            self._representative_match_cache[normalized] = res
'''
if old not in text:
    raise SystemExit("representative match anchor not found")
text = text.replace(old, new, 1)
old = '''        tokens = normalized.split()
        if any(token in self.REPRESENTATIVE_NOISE_TOKENS for token in tokens):
            return False
'''
new = '''        tokens = normalized.split()
        if any(token in {"BOS", "KADRO"} for token in tokens) and len(tokens) >= 2:
            return True
        if any(token in self.REPRESENTATIVE_NOISE_TOKENS for token in tokens):
            return False
'''
if old not in text:
    raise SystemExit("probable representative anchor not found")
text = text.replace(old, new, 1)
old = '        unit_target = float(round(unit_target or 0))\n'
new = '        unit_target = float(unit_target or 0)\n'
if old not in text:
    raise SystemExit("unit rounding anchor not found")
text = text.replace(old, new, 1)
path.write_text(text)
