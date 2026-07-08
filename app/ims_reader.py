import pandas as pd


class IMSReader:

    def __init__(self, path):

        self.path = path

        self.excel = pd.ExcelFile(path)

    def get_sheet_names(self):

        return self.excel.sheet_names

    def read_sheet(self, sheet):

        return pd.read_excel(

            self.path,

            sheet_name=sheet

        )

    def read_all(self):

        data = {}

        for sheet in self.get_sheet_names():

            data[sheet] = self.read_sheet(

                sheet

            )

        return data
