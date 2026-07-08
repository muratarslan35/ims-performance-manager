from app.extensions import db

from app.models import (
    IMSUpload,
    IMSRawData,
    IMSSummary,
    Product,
    Representative
)

from app.ims_reader import IMSReader


class IMSImporter:

    def __init__(self, upload_id, path):

        self.upload_id = upload_id

        self.path = path

        self.reader = IMSReader(path)

    def run(self):

        sheets = self.reader.read_all()

        for sheet_name, dataframe in sheets.items():

            self.import_sheet(
                sheet_name,
                dataframe
            )

        self.create_summary()

        db.session.commit()

    def import_sheet(
        self,
        sheet_name,
        dataframe
    ):

        for _, row in dataframe.iterrows():

            raw = IMSRawData(

                upload_id=self.upload_id,

                sheet_name=sheet_name,

                representative="",

                manager="",

                product="",

                competitor="",

                brick="",

                market="",

                unit=0,

                tl=0,

                market_share=0,

                raw_json=row.to_json(
                    force_ascii=False
                )

            )

            db.session.add(raw)

    def create_summary(self):

        pass
