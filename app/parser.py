import pandas as pd

from app.models import Product
from app.models import Representative


class IMSParser:

    def __init__(self):

        self.products = Product.query.all()

        self.representatives = Representative.query.all()

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

        representative = self.find_representative(row)

        product = self.find_product(row)

        return {

            "representative": representative,

            "product": product,

            "competitor": self.find_competitor(row),

            "unit": self.find_unit(row),

            "tl": self.find_tl(row),

            "market_share": self.find_market_share(row),

            "brick": self.find_brick(row),

            "raw": row.to_dict()

        }

    def find_representative(self, row):

        text = " ".join(

            map(str, row.values)

        ).upper()

        for rep in self.representatives:

            if rep.rep_name.upper() in text:

                return rep.rep_name

        return None

    def find_product(self, row):

        text = " ".join(

            map(str, row.values)

        ).upper()

        for product in self.products:

            if product.product_name.upper() in text:

                return product.product_name

            if product.ims_name:

                if product.ims_name.upper() in text:

                    return product.product_name

        return None

    def find_competitor(self, row):

        return None

    def find_unit(self, row):

        return 0

    def find_tl(self, row):

        return 0

    def find_market_share(self, row):

        return 0

    def find_brick(self, row):

        return None
