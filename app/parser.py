import pandas as pd

from app.mapping import IMSMapper


class IMSParser:

    def __init__(self):

        self.mapper = IMSMapper()

    def parse_sheet(

        self,

        sheet_name,

        dataframe

    ):

        records = []

        for _, row in dataframe.iterrows():

            record = self.parse_row(row)

            if record:

                records.append(record)

        return records

    def parse_row(self, row):

        text = " ".join(

            map(str, row.values)

        )

        representative = self.mapper.map_representative(
            text
        )

        product = self.mapper.map_product(
            text
        )

        return {

            "representative":

                representative.rep_name

                if representative else None,

            "product":

                product.product_name

                if product else None,

            "competitor":

                self.find_competitor(row),

            "unit":

                self.find_unit(row),

            "tl":

                self.find_tl(row),

            "market_share":

                self.find_market_share(row),

            "brick":

                self.find_brick(row),

            "raw":

                row.to_dict()

        }

    def find_competitor(self, row):

        return None

    def find_unit(self, row):

        for value in row.values:

            number = self.mapper.find_number(value)

            if number > 0:

                return number

        return 0

    def find_tl(self, row):

        return 0

    def find_market_share(self, row):

        return 0

    def find_brick(self, row):

        return None
