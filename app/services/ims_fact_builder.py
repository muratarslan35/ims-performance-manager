from app.extensions import db
from app.models import IMSRawData, IMSFact, IMSUpload
from app.services.alias_service import AliasService


class IMSFactBuilderService:

    @classmethod
    def build(cls, upload_id):

        AliasService.warmup()

        IMSFact.query.filter_by(
            upload_id=upload_id
        ).delete(
            synchronize_session=False
        )

        db.session.flush()

        upload = IMSUpload.query.get(upload_id)

        rows = IMSRawData.query.filter_by(
            upload_id=upload_id
        ).all()

        created = 0
        skipped = 0

        for row in rows:

            rep = AliasService.find_representative(
                row.representative
            )

            prod = AliasService.find_product(
                row.product
            )

            if (
                not rep["matched"]
                or
                not prod["matched"]
            ):
                skipped += 1
                continue

            fact = IMSFact(

                upload_id=row.upload_id,

                representative_id=rep["object"].id,

                product_id=prod["object"].id,

                year=upload.year,

                month=upload.month,

                week=upload.week,

                sheet_type=row.sheet_name,

                unit=row.unit or 0,

                tl=row.tl or 0,

                market_share=row.market_share or 0,

                value_share=row.value_share or 0,

                growth=row.growth or 0

            )

            db.session.add(fact)

            created += 1

        db.session.commit()

        return {

            "created": created,

            "skipped": skipped

        }
