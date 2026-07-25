from app.extensions import db

from app.ims_reader import IMSReader
from app.parser import IMSParser
from app.summary_engine import SummaryEngine

from app.models import IMSRawData


class IMSImporter:

    def __init__(self, upload_id, path):

        self.upload_id = upload_id

        self.path = path

        self.reader = IMSReader(path)

        self.parser = IMSParser()

    def run(self):

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

        db.session.commit()

        SummaryEngine(

            self.upload_id

        ).run()

    def import_records(

        self,

        sheet_name,

        records

    ):

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

                brick=record.get(
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

    def create_summary(self):

        SummaryEngine(

            self.upload_id

        ).run()
