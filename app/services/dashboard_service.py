from app.models import IMSUpload, Product, RecoverySummary, Representative, Target


class DashboardService:
    """Read-only dashboard queries kept independent from the import pipeline."""

    def load_counts(self):
        return {
            "total_products": Product.query.filter_by(is_active=True).count(),
            "total_representatives": Representative.query.filter_by(active=True).count(),
            "total_targets": Target.query.count(),
            "total_uploads": IMSUpload.query.count(),
            "completed_uploads": IMSUpload.query.filter_by(status="COMPLETED").count(),
            "failed_uploads": IMSUpload.query.filter_by(status="FAILED").count(),
            "processing_uploads": IMSUpload.query.filter_by(status="PROCESSING").count(),
        }

    def load_last_upload(self):
        upload = IMSUpload.query.order_by(IMSUpload.uploaded_at.desc()).first()
        return {
            "last_upload": upload,
            "latest_upload_file": upload.file_name if upload else None,
            "latest_upload_date": upload.uploaded_at if upload else None,
            "latest_upload_status": upload.status if upload else None,
        }

    def load_recovery(self):
        rows = RecoverySummary.query.all()
        counts = {"risk_products": 0, "critical_products": 0, "warning_products": 0, "healthy_products": 0}
        for row in rows:
            if row.status == "Kritik":
                counts["critical_products"] += 1
            elif row.status == "Riskli":
                counts["risk_products"] += 1
            elif row.status == "Takip":
                counts["warning_products"] += 1
            else:
                counts["healthy_products"] += 1
        return {**counts, "recovery_summary": rows}

    @staticmethod
    def load_prime_summary():
        return {"main_prime": 0, "ciro_prime": 0, "total_prime": 0, "status": "-"}

    @staticmethod
    def load_quarter_summary():
        return {"completed_products": 0, "failed_products": 0, "total_percent": 0}

    @staticmethod
    def build_ai_messages(recovery):
        messages = []
        if recovery["critical_products"]:
            messages.append(f"{recovery['critical_products']} kritik ürün bulunuyor.")
        if recovery["risk_products"]:
            messages.append(f"{recovery['risk_products']} riskli ürün takip edilmeli.")
        if recovery["warning_products"]:
            messages.append(f"{recovery['warning_products']} ürün takip seviyesinde.")
        if not messages:
            messages.append("Recovery açısından riskli ürün bulunmuyor.")
        return messages

    def run(self):
        recovery = self.load_recovery()
        return {
            **self.load_counts(),
            **self.load_last_upload(),
            **recovery,
            "prime_summary": self.load_prime_summary(),
            "quarter_summary": self.load_quarter_summary(),
            "ai_messages": self.build_ai_messages(recovery),
        }

    @classmethod
    def health(cls):
        return {"service": "DashboardService", "status": "READY", "version": "2.0.0"}
