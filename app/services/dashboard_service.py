from app.models import (
    Product,
    Representative,
    IMSUpload,
    Target,
    RecoverySummary
)


class DashboardService:

    def __init__(

        self

    ):

        pass


    def load_counts(

        self

    ):

        return {

            "total_products":

                Product.query.filter_by(

                    is_active=True

                ).count(),

            "total_representatives":

                Representative.query.filter_by(

                    active=True

                ).count(),

            "total_targets":

                Target.query.count(),

            "total_uploads":

                IMSUpload.query.count(),

            "completed_uploads":

                IMSUpload.query.filter_by(

                    status="Hazır"

                ).count(),

            "failed_uploads":

                IMSUpload.query.filter_by(

                    status="Hata"

                ).count(),

            "processing_uploads":

                IMSUpload.query.filter_by(

                    status="İşleniyor"

                ).count()

        }


    def load_last_upload(

        self

    ):

        upload = IMSUpload.query.order_by(

            IMSUpload.uploaded_at.desc()

        ).first()

        if upload is None:

            return {

                "last_upload": None,

                "latest_upload_file": None,

                "latest_upload_date": None,

                "latest_upload_status": None

            }

        return {

            "last_upload":

                upload,

            "latest_upload_file":

                upload.file_name,

            "latest_upload_date":

                upload.uploaded_at,

            "latest_upload_status":

                upload.status

        }


    def load_recovery(

        self

    ):

        rows = RecoverySummary.query.all()

        risk = 0

        critical = 0

        warning = 0

        healthy = 0

        for row in rows:

            if row.status == "Kritik":

                critical += 1

            elif row.status == "Riskli":

                risk += 1

            elif row.status == "Takip":

                warning += 1

            else:

                healthy += 1

        return {

            "risk_products":

                risk,

            "critical_products":

                critical,

            "warning_products":

                warning,

            "healthy_products":

                healthy,

            "recovery_summary":

                rows

        }

      def load_prime_summary(

        self

    ):

        return {

            "main_prime": 0,

            "ciro_prime": 0,

            "total_prime": 0,

            "status": "-"

        }


    def load_quarter_summary(

        self

    ):

        return {

            "completed_products": 0,

            "failed_products": 0,

            "total_percent": 0

        }


    def build_ai_messages(

        self,

        recovery

    ):

        messages = []

        if recovery[

            "critical_products"

        ] > 0:

            messages.append(

                f'{recovery["critical_products"]} kritik ürün bulunuyor.'

            )

        if recovery[

            "risk_products"

        ] > 0:

            messages.append(

                f'{recovery["risk_products"]} riskli ürün takip edilmeli.'

            )

        if recovery[

            "warning_products"

        ] > 0:

            messages.append(

                f'{recovery["warning_products"]} ürün takip seviyesinde.'

            )

        if (

            recovery["critical_products"] == 0

            and

            recovery["risk_products"] == 0

        ):

            messages.append(

                "Recovery açısından riskli ürün bulunmuyor."

            )

        return messages


    def run(

        self

    ):

        counts = self.load_counts()

        upload = self.load_last_upload()

        recovery = self.load_recovery()

        prime = self.load_prime_summary()

        quarter = self.load_quarter_summary()

        return {

            **counts,

            **upload,

            **recovery,

            "prime_summary":

                prime,

            "quarter_summary":

                quarter,

            "ai_messages":

                self.build_ai_messages(

                    recovery

                )

        }


    @classmethod
    def health(

        cls

    ):

        return {

            "service":

                "DashboardService",

            "status":

                "READY",

            "version":

                "1.0.0"

        }
