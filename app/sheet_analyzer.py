import re


class SheetAnalyzer:

    def __init__(self, dataframe):

        self.df = dataframe

        self.columns = [
            str(col).strip()
            for col in dataframe.columns
        ]

    def analyze(self):

        return {

            "header_row": self.find_header_row(),

            "representative_column": self.find_representative_column(),

            "product_column": self.find_product_column(),

            "unit_column": self.find_unit_column(),

            "tl_column": self.find_tl_column(),

            "market_share_column": self.find_market_share_column(),

            "brick_column": self.find_brick_column()

        }

    def find_header_row(self):

        return 0

    def find_representative_column(self):

        keywords = [

            "TEMSİLCİ",

            "TEMSILCI",

            "MÜMESSİL",

            "REP",

            "PERSONEL",

            "SATIŞ TEMSİLCİSİ"

        ]

        return self.search_column(

            keywords

        )

    def find_product_column(self):

        keywords = [

            "ÜRÜN",

            "URUN",

            "PRODUCT",

            "MARKA"

        ]

        return self.search_column(

            keywords

        )

    def find_unit_column(self):

        keywords = [

            "KUTU",

            "ADET",

            "UNIT",

            "QTY"

        ]

        return self.search_column(

            keywords

        )

    def find_tl_column(self):

        keywords = [

            "TL",

            "TTS",

            "CIRO",

            "NET SATIŞ",

            "NET SATIS",

            "TUTAR"

        ]

        return self.search_column(

            keywords

        )

    def find_market_share_column(self):

        keywords = [

            "PAZAR",

            "PAY",

            "MARKET",

            "SHARE"

        ]

        return self.search_column(

            keywords

        )

    def find_brick_column(self):

        keywords = [

            "BRICK",

            "BRİCK"

        ]

        return self.search_column(

            keywords

        )

    def search_column(

        self,

        keywords

    ):

        for column in self.columns:

            upper = column.upper()

            for keyword in keywords:

                if keyword in upper:

                    return column

        return None

    def clean_number(

        self,

        value

    ):

        if value is None:

            return 0

        text = str(value)

        text = text.replace(".", "")

        text = text.replace(",", ".")

        text = re.sub(

            r"[^\d.-]",

            "",

            text

        )

        try:

            return float(text)

        except:

            return 0
