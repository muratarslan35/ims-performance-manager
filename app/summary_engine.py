from sqlalchemy import func

from app.extensions import db

from app.models import (
    IMSRawData,
    IMSSummary,
    Representative,
    Product
)


class SummaryEngine:

    def __init__(self, upload_id):

        self.upload_id = upload_id

    def run(self):

        IMSSummary.query.filter_by(

            upload_id=self.upload_id

        ).delete()

        db.session.commit()

        self.create_summary()

        db.session.commit()

    def create_summary(self):

        data = db.session.query(

            IMSRawData.representative,

            IMSRawData.product,

            func.sum(

                IMSRawData.unit

            ),

            func.sum(

                IMSRawData.tl

            ),

            func.avg(

                IMSRawData.market_share

            )

        ).filter(

            IMSRawData.upload_id == self.upload_id

        ).group_by(

            IMSRawData.representative,

            IMSRawData.product

        ).all()

        for row in data:

            rep = Representative.query.filter_by(

                rep_name=row[0]

            ).first()

            product = Product.query.filter_by(

                product_name=row[1]

            ).first()

            summary = IMSSummary(

                upload_id=self.upload_id,

                representative_id=rep.id if rep else None,

                product_id=product.id if product else None,

                unit=row[2] or 0,

                tl=row[3] or 0,

                market_share=row[4] or 0

            )

            db.session.add(summary)
