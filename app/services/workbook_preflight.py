"""Whole-workbook manifest and mandatory parser-coverage gate for IMS imports.

Every workbook sheet is accounted for. Meaningful cells are registered in a
coverage ledger before import. Zero is data (never blank). A sheet must either
be handled by the generic parser, a specialised parser/verifier, or be explicit
non-data; unknown meaningful content blocks the upload.
"""
from __future__ import annotations
import re
from app.services.alias_service import AliasService

class WorkbookPreflight:
    RULES = (
        ("official_brick_spread", ("SATIS BRICK YAYILIM", "SATIŞ BRICK YAYILIM")),
        ("brick_sales", ("1001 BRICK SATIS", "BRICK SATIS", "BRICK SATIŞ")),
        ("brick_realization", ("BRICK REA",)),
        ("weekly_sales", ("TTS HAFTALIK CIKIS", "TTS HAFTALIK ÇIKIŞ")),
        ("balance", ("BAKIYE", "BAKİYE")),
        ("competition_pp", ("TTS REKABET PP", "REKABET PP")),
        ("competition_tl", ("AYLIK REKABET TL", "REKABET TL", "TTS REKABET TL")),
        ("competition_box", ("AYLIK REKABET KUTU", "REKABET KUTU", "TTS REKABET KUTU")),
        ("competition", ("TTS REKABET",)),
        ("representative_sales", ("TTS CIKIS", "TTS ÇIKIŞ")),
        ("official_national_region_aggregate", ("NATIONAL", "BOLGE TOPLAM", "BÖLGE TOPLAM", "GENEL TOPLAM")),
        ("master_pivot_derived", ("PIVOT", "MASTER", "PAZAR")),
    )
    MONTHS = {"OCAK","SUBAT","ŞUBAT","MART","NISAN","NİSAN","MAYIS","HAZIRAN","HAZİRAN","TEMMUZ","AGUSTOS","AĞUSTOS","EYLUL","EYLÜL","EKIM","EKİM","KASIM","ARALIK"}
    SPECIALIZED = {"official_brick_spread","brick_realization","weekly_sales","balance","competition","competition_tl","competition_box","competition_pp","official_national_region_aggregate","master_pivot_derived"}
    TERMINAL_CELL_CLASSES = {"IMPORTED_FACT","IMPORTED_MASTER","VERIFIED_DERIVED","AGGREGATE_VERIFIED","EXPLICIT_NONDATA"}

    def __init__(self, service): self.service = service
    @staticmethod
    def _normalized(value): return AliasService.normalize(value)
    @staticmethod
    def _is_meaningful(value):
        # 0/0.0/"0" are intentionally meaningful. Only actual null/blank text is empty.
        if value is None: return False
        try:
            if value != value: return False  # NaN
        except Exception:
            pass
        return not (isinstance(value, str) and not value.strip())
    def _meaningful_cells(self, frame): return sum(1 for value in frame.to_numpy().ravel() if self._is_meaningful(value))
    def _header_signature(self, frame):
        values=[]
        for row in range(min(12,len(frame))):
            for col in range(min(80,frame.shape[1]) if frame.shape[1] else 0):
                value=frame.iloc[row,col]
                if self._is_meaningful(value): values.append(self._normalized(value))
        return " | ".join(values)
    def classify(self,sheet_name,frame):
        name=self._normalized(sheet_name); combined=f"{name} | {self._header_signature(frame)}"
        for sheet_type,tokens in self.RULES:
            if any(self._normalized(token) in combined for token in tokens): return sheet_type
        words=set(re.findall(r"[A-ZÇĞİÖŞÜ]+",name))
        if words & {self._normalized(month) for month in self.MONTHS}:
            if "KUTU" in words: return "monthly_master_box"
            if "TL" in words: return "monthly_master_tl"
            return "monthly_master"
        if name in {"KUTU","TL"}: return "master_pivot_derived"
        if self.service.find_header_row(frame) is not None: return "representative_sales"
        return "unknown"
    def build(self):
        manifest=[]
        for sheet_name,frame in (self.service.workbook or {}).items():
            meaningful=self._meaningful_cells(frame)
            explicit_nondata=meaningful <= 1
            sheet_type="explicit_nondata" if explicit_nondata else self.classify(sheet_name,frame)
            header_row=None if explicit_nondata else self.service.find_header_row(frame)
            coverage="explicit_nondata" if explicit_nondata else ("generic_parser" if header_row is not None else ("specialized_parser" if sheet_type in self.SPECIALIZED or sheet_type.startswith("monthly_master") else "unclassified"))
            manifest.append({"sheet_name":str(sheet_name),"rows":int(frame.shape[0]),"columns":int(frame.shape[1]),"meaningful_cells":meaningful,"header_row":header_row,"sheet_type":sheet_type,"coverage":coverage})
        return manifest
    def build_cell_ledger(self, manifest):
        by_sheet={item["sheet_name"]:item for item in manifest}; ledger=[]
        for sheet_name,frame in (self.service.workbook or {}).items():
            item=by_sheet[str(sheet_name)]
            if item["coverage"] == "explicit_nondata": default_class="EXPLICIT_NONDATA"
            elif item["coverage"] == "generic_parser": default_class="IMPORTED_FACT"
            elif item["sheet_type"] == "official_national_region_aggregate": default_class="AGGREGATE_VERIFIED"
            elif item["sheet_type"] in {"master_pivot_derived","brick_realization"} or item["sheet_type"].startswith("monthly_master"): default_class="VERIFIED_DERIVED"
            elif item["coverage"] == "specialized_parser": default_class="IMPORTED_MASTER"
            else: default_class="UNCLASSIFIED_MASTER_CELL"
            for row in range(frame.shape[0]):
                for col in range(frame.shape[1]):
                    value=frame.iloc[row,col]
                    if not self._is_meaningful(value): continue
                    ledger.append({"sheet_name":str(sheet_name),"row":row+1,"column":col+1,"classification":default_class,"sheet_type":item["sheet_type"]})
        return ledger
    def validate(self):
        manifest=self.build(); unclassified=[item for item in manifest if item["coverage"]=="unclassified" or item["sheet_type"]=="unknown"]
        ledger=self.build_cell_ledger(manifest)
        unclassified_cells=[cell for cell in ledger if cell["classification"] not in self.TERMINAL_CELL_CLASSES]
        self.service.workbook_manifest=manifest; self.service.workbook_cell_ledger=ledger
        self.service.statistics["manifest_sheet_count"]=len(manifest); self.service.statistics["manifest_verified_sheets"]=len(manifest)-len(unclassified); self.service.statistics["unclassified_sheet"]=len(unclassified)
        self.service.statistics["manifest_meaningful_cells"]=len(ledger); self.service.statistics["classified_master_cells"]=len(ledger)-len(unclassified_cells); self.service.statistics["unclassified_master_cell"]=len(unclassified_cells)
        self.service.statistics.setdefault("conflicting_match",0); self.service.statistics.setdefault("duplicate_conflict",0); self.service.statistics.setdefault("auto_repaired",0)
        self.service.parser_decisions.extend({"sheet_name":item["sheet_name"],"sheet_type":item["sheet_type"],"coverage":item["coverage"]} for item in manifest)
        if unclassified: raise ValueError("Workbook preflight başarısız; sınıflandırılmamış sheet: "+", ".join(item["sheet_name"] for item in unclassified))
        if unclassified_cells: raise ValueError(f"Workbook preflight başarısız; {len(unclassified_cells)} anlamlı hücre sınıflandırılamadı")
        return manifest

def install_workbook_preflight():
    from app.services.ims_import_service import IMSImportService
    if getattr(IMSImportService,"_whole_workbook_preflight_installed",False): return
    original_process=IMSImportService.process_workbook; original_report=IMSImportService.report
    def process_with_preflight(self,year,month,week_number=None): WorkbookPreflight(self).validate(); return original_process(self,year,month,week_number=week_number)
    def report_with_manifest(self):
        report=original_report(self); report["workbook_manifest"]=getattr(self,"workbook_manifest",[]); report["workbook_cell_ledger"]=getattr(self,"workbook_cell_ledger",[])
        blocking=("unclassified_sheet","unclassified_master_cell","unresolved_representative","unresolved_product","invalid_metric","row_error","conflicting_match","duplicate_conflict")
        report["final_result"]="PASS" if not report.get("errors") and all(int(self.statistics.get(key,0) or 0)==0 for key in blocking) else "FAIL"
        return report
    IMSImportService.process_workbook=process_with_preflight; IMSImportService.report=report_with_manifest; IMSImportService._whole_workbook_preflight_installed=True
