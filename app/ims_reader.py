import pandas as pd


class IMSReader:

    def __init__(self, path):

        self.path = path

        self.excel = pd.ExcelFile(path)

        self.sheet_names = self.excel.sheet_names


    def get_sheet_names(self):

        return self.sheet_names


    def read_sheet(self, sheet_name):

        return pd.read_excel(

            self.path,

            sheet_name=sheet_name

        )


    def read_all(self):

        sheets = {}

        for sheet in self.sheet_names:

            sheets[sheet] = self.read_sheet(

                sheet

            )

        return sheets


    def detect_sheet_type(self, sheet_name):

        name = sheet_name.upper()

        if "KUTU" in name:
            return "UNIT"

        if "TTS" in name:
            return "TL"

        if "BRICK" in name:
            return "BRICK"

        if "PAZAR" in name:
            return "MARKET"

        if "REKABET" in name:
            return "COMPETITOR"

        return "UNKNOWN"


    def get_sheet_information(self):

        info = []

        for sheet in self.sheet_names:

            info.append({

                "sheet_name": sheet,

                "sheet_type": self.detect_sheet_type(sheet),

                "row_count": len(

                    self.read_sheet(sheet)

                )

            })

        return info
