from app.mapping import IMSMapper
from app.sheet_analyzer import SheetAnalyzer


class IMSParser:

    def __init__(self):

        self.mapper = IMSMapper()

    def parse_sheet(

        self,

        sheet_name,

        dataframe

    ):

        analyzer = SheetAnalyzer(
            dataframe
        )

        columns = analyzer.analyze()

        records = []

        for _, row in dataframe.iterrows():

            record = self.parse_row(

                row,

                columns

            )

            if record:

                records.append(record)

        return records

    def parse_row(

        self,

        row,

        columns

    ):

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

                self.find_competitor(
                    row,
                    columns
                ),

            "unit":

                self.find_unit(
                    row,
                    columns
                ),

            "tl":

                self.find_tl(
                    row,
                    columns
                ),

            "market_share":

                self.find_market_share(
                    row,
                    columns
                ),

            "brick":

                self.find_brick(
                    row,
                    columns
                ),

            "raw":

                row.to_dict()

        }

    def find_competitor(

        self,

        row,

        columns

    ):

        return None

    def find_unit(

        self,

        row,

        columns

    ):

        column = columns.get(
            "unit_column"
        )

        if column and column in row.index:

            return self.mapper.find_number(
                row[column]
            )

        return 0

    def find_tl(

        self,

        row,

        columns

    ):

        column = columns.get(
            "tl_column"
        )

        if column and column in row.index:

            return self.mapper.find_number(
                row[column]
            )

        return 0

    def find_market_share(

        self,

        row,

        columns

    ):

        column = columns.get(
            "market_share_column"
        )

        if column and column in row.index:

            return self.mapper.find_number(
                row[column]
            )

        return 0

    def find_brick(

        self,

        row,

        columns

    ):

        column = columns.get(
            "brick_column"
        )

        if column and column in row.index:

            return self.mapper.clean_text(
                row[column]
            )

        return None
