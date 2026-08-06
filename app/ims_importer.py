"""Master orchestrator for the IMS file import pipeline."""

from typing import List, Dict, Any, Type, Protocol
from app.extensions import db
from app.ims_reader import IMSReader
from app.parser import IMSParser
from app.summary_engine import SummaryEngine
from app.models import IMSRawData
from app.services.competition_import_service import CompetitionImportService


class SheetImporter(Protocol):
    """Protocol defining the interface for modular sheet importers."""

    @classmethod
    def can_handle(cls, sheet_name: str) -> bool:
        ...

    @classmethod
    def import_records(cls, upload_id: int, sheet_name: str, records: List[Dict[str, Any]]) -> int:
        ...


class CompetitionImporter:
    """Specialized importer dispatcher routing pre-parsed records to CompetitionImportService."""

    SUPPORTED_COMPETITION_SHEETS = {
        "HAZİRAN KUTU",
        "HAZİRAN TL",
        "KUTU",
        "TL",
        "AYLIK REKABET KUTU",
        "AYLIK REKABET TL",
        "PAZAR",
    }

    @classmethod
    def can_handle(cls, sheet_name: str) -> bool:
        """Determines if the sheet belongs to competition extension datasets."""
        return str(sheet_name).strip().upper() in cls.SUPPORTED_COMPETITION_SHEETS

    @classmethod
    def import_records(cls, upload_id: int, sheet_name: str, records: List[Dict[str, Any]]) -> int:
        """Passes pre-parsed records directly to CompetitionImportService business layer."""
        service = CompetitionImportService(upload_id=upload_id)
        return service.import_records(records, sheet_name)


# Extensible Importer Registry for future domain-specific importers
IMPORTERS: List[Type[SheetImporter]] = [
    CompetitionImporter,
]


class IMSImporter:
    """Master orchestrator managing the single transaction IMS file import pipeline."""

    def __init__(self, upload_id: int, path: str) -> None:
        self.upload_id = upload_id
        self.path = path
        self.reader = IMSReader(path)
        self.parser = IMSParser()

    def run(self) -> None:
        """Executes the master import flow with single transaction commit and rollback guarantees."""
        try:
            sheets = self.reader.read_all()

            for sheet_name, dataframe in sheets.items():
                records = self.parser.parse_sheet(
                    sheet_name,
                    dataframe
                )

                self.import_records(
                    sheet_name,
                    records
                )

            # Run summary engine post-processing before final commit
            SummaryEngine(
                self.upload_id
            ).run()

            db.session.commit()
            
        except Exception:
            db.session.rollback()
            raise

    def import_records(
        self,
        sheet_name: str,
        records: List[Dict[str, Any]]
    ) -> None:
        """Dispatcher method routing records via extensible registry or fallback storage."""
        matched_importer = None
        for importer in IMPORTERS:
            if importer.can_handle(sheet_name):
                matched_importer = importer
                break

        if matched_importer:
            matched_importer.import_records(self.upload_id, sheet_name, records)
            return

        # Fallback for un-migrated sheets to IMSRawData
        for record in records:
            raw = IMSRawData(
                upload_id=self.upload_id,
                sheet_name=sheet_name,
                representative=record.get(
                    "representative"
                ),
                product=record.get(
                    "product"
                ),
                competitor=record.get(
                    "competitor"
                ),
                    "brick"
                ),
                unit=record.get(
                    "unit",
                    0
                ),
                tl=record.get(
                    "tl",
                    0
                ),
                market_share=record.get(
                    "market_share",
                    0
                ),
                raw_json=str(
                    record.get(
                        "raw",
                        {}
                    )
                )
            )

            db.session.add(raw)

    def create_summary(self) -> None:
        """Standalone helper trigger for summary generation."""
        SummaryEngine(
            self.upload_id
        ).run()
