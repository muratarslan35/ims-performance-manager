from app.models import Product
from app.models import Representative


class IMSMapper:

    def __init__(self):

        self.products = Product.query.filter_by(
            is_active=True
        ).all()

        self.representatives = Representative.query.filter_by(
            active=True
        ).all()

    def map_product(self, text):

        if text is None:
            return None

        value = str(text).upper().strip()

        for product in self.products:

            if product.product_name:

                if product.product_name.upper() in value:

                    return product

            if product.ims_name:

                if product.ims_name.upper() in value:

                    return product

        return None

    def map_representative(self, text):

        if text is None:
            return None

        value = str(text).upper().strip()

        for rep in self.representatives:

            if rep.rep_name.upper() in value:

                return rep

            if rep.rep_code:

                if rep.rep_code.upper() in value:

                    return rep

            if rep.ims_code:

                if rep.ims_code.upper() in value:

                    return rep

        return None

    def find_number(self, value):

        try:

            value = str(value)

            value = value.replace(".", "")

            value = value.replace(",", ".")

            return float(value)

        except:

            return 0

    def clean_text(self, value):

        if value is None:

            return ""

        return str(value).strip()
