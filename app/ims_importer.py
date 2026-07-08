from app.extensions import db

from app.ims_reader import IMSReader
from app.parser import IMSParser

from app.models import (
    IMSRawData,
    IMSSummary
)


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

        self.create_summary()

        db.session.commit()


    def import_records(

        self,

        sheet_name,

        records

    ):

        for record in records:

            raw = IMSRawData(

                upload_id=self.upload_id,

                sheet_name=sheet_name,

                representative=record["representative"],

                product=record["product"],

                competitor=record["competitor"],

                brick=record["brick"],

                unit=record["unit"],

                tl=record["tl"],

                market_share=record["market_share"],

                raw_json=str(record["raw"])

            )

            db.session.add(raw)


    def create_summary(self):

        pass
