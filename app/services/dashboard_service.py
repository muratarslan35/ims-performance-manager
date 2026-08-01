from sqlalchemy import func

from app.extensions import db
from app.models import IMSUpload, IMSSummary, Product, RecoverySummary, Representative, Target

MONTH_NAMES = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


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

    def load_overall_stats(self):
        total_tl = db.session.query(func.sum(IMSSummary.tl)).scalar() or 0
        target_tl = db.session.query(func.sum(Target.tl_target)).scalar() or 0
        pct = round((total_tl / target_tl * 100), 1) if target_tl > 0 else 0
        return {
            "overall_realization_tl": round(total_tl, 0),
            "overall_target_tl": round(target_tl, 0),
            "overall_percent": pct,
        }

    def load_product_performance(self):
        products = (
            Product.query.filter_by(is_active=True)
            .order_by(Product.display_order)
            .all()
        )
        result = []
        total_ciro = 0.0
        for p in products:
            total_tl = (
                db.session.query(func.sum(IMSSummary.tl))
                .filter(IMSSummary.product_id == p.id)
                .scalar() or 0
            )
            target_tl = (
                db.session.query(func.sum(Target.tl_target))
                .filter(Target.product_id == p.id)
                .scalar() or 0
            )
            pct = round((total_tl / target_tl * 100), 1) if target_tl > 0 else 0
            if pct >= 90:
                status = "Tamamlandı"
            elif pct >= 70:
                status = "Devam Ediyor"
            else:
                status = "Riskli"
            result.append({
                "product_name": p.product_name,
                "total_tl": round(total_tl, 0),
                "target_tl": round(target_tl, 0),
                "realization_percent": pct,
                "status": status,
            })
            total_ciro += total_tl
        return {"product_performance": result, "total_ciro": round(total_ciro, 0)}

    def load_top_representatives(self):
        reps = Representative.query.filter_by(active=True).all()
        rep_stats = []
        for rep in reps:
            total_tl = (
                db.session.query(func.sum(IMSSummary.tl))
                .filter(IMSSummary.representative_id == rep.id)
                .scalar() or 0
            )
            target_tl = (
                db.session.query(func.sum(Target.tl_target))
                .filter(Target.representative_id == rep.id)
                .scalar() or 0
            )
            bonus = (
                db.session.query(func.sum(IMSSummary.bonus_amount))
                .filter(IMSSummary.representative_id == rep.id)
                .scalar() or 0
            )
            pct = round((total_tl / target_tl * 100), 1) if target_tl > 0 else 0
            rep_stats.append({
                "rep_name": rep.rep_name,
                "city": rep.city or "-",
                "total_tl": round(total_tl, 0),
                "realization_percent": pct,
                "bonus_amount": round(bonus, 0),
            })
        rep_stats.sort(key=lambda x: x["realization_percent"], reverse=True)
        for i, r in enumerate(rep_stats):
            r["rank"] = i + 1
        return {"top_representatives": rep_stats[:10]}

    def load_monthly_trend(self):
        rows = (
            db.session.query(
                IMSSummary.year,
                IMSSummary.month,
                func.sum(IMSSummary.tl).label("total_tl"),
            )
            .group_by(IMSSummary.year, IMSSummary.month)
            .order_by(IMSSummary.year, IMSSummary.month)
            .limit(12)
            .all()
        )
        labels = [f"{MONTH_NAMES[r.month - 1]} {r.year}" for r in rows]
        realization = [round(r.total_tl or 0, 0) for r in rows]
        targets = []
        for r in rows:
            t = (
                db.session.query(func.sum(Target.tl_target))
                .filter(Target.year == r.year, Target.month == r.month)
                .scalar() or 0
            )
            targets.append(round(t, 0))
        return {
            "monthly_trend": {
                "labels": labels,
                "realization": realization,
                "target": targets,
            }
        }

    def load_market_share_trend(self):
        rows = (
            db.session.query(
                IMSSummary.year,
                IMSSummary.month,
                func.avg(IMSSummary.market_share).label("avg_share"),
            )
            .group_by(IMSSummary.year, IMSSummary.month)
            .order_by(IMSSummary.year, IMSSummary.month)
            .limit(12)
            .all()
        )
        return {
            "market_share_trend": {
                "labels": [f"{MONTH_NAMES[r.month - 1]} {r.year}" for r in rows],
                "values": [round(r.avg_share or 0, 2) for r in rows],
            }
        }

    def load_city_performance(self):
        rows = (
            db.session.query(
                Representative.city,
                func.sum(IMSSummary.tl).label("total_tl"),
                func.sum(Target.tl_target).label("target_tl"),
            )
            .join(IMSSummary, IMSSummary.representative_id == Representative.id)
            .outerjoin(
                Target,
                (Target.representative_id == Representative.id)
                & (Target.year == IMSSummary.year)
                & (Target.month == IMSSummary.month),
            )
            .filter(Representative.city.isnot(None))
            .group_by(Representative.city)
            .all()
        )
        city_perf = {}
        for city, tl, target in rows:
            if city:
                pct = round((tl / target * 100), 1) if (target and target > 0) else 0
                city_perf[city] = {"tl": round(tl or 0, 0), "percent": pct}
        return {"city_performance": city_perf}

    def load_active_quarter(self):
        upload = IMSUpload.query.order_by(IMSUpload.uploaded_at.desc()).first()
        return {"active_quarter": upload.quarter if upload else "-"}

    def load_recent_uploads(self):
        uploads = IMSUpload.query.order_by(IMSUpload.uploaded_at.desc()).limit(5).all()
        return {"recent_uploads": uploads}

    def load_ai_scores(self, recovery, overall_stats):
        total_products = (
            Product.query.filter_by(is_active=True).count() or 1
        )
        risky = recovery.get("critical_products", 0) + recovery.get("risk_products", 0)
        risk_score = round(min(100, (risky / total_products) * 100))
        opportunity_score = 100 - risk_score
        pct = overall_stats.get("overall_percent", 0)
        goal_probability = round(min(100, pct), 1)
        total_tl = overall_stats.get("overall_realization_tl", 0)
        target_tl = overall_stats.get("overall_target_tl", 0)
        lost = max(0, target_tl - total_tl)
        return {
            "ai_scores": {
                "risk_score": risk_score,
                "opportunity_score": opportunity_score,
                "goal_probability": goal_probability,
                "expected_prime": round(total_tl, 0),
                "lost_prime": round(lost, 0),
                "additional_prime": round(total_tl * 0.05, 0),
            }
        }

    def run(self):
        counts = self.load_counts()
        recovery = self.load_recovery()
        last_upload = self.load_last_upload()
        overall = self.load_overall_stats()
        product_perf = self.load_product_performance()
        top_reps = self.load_top_representatives()
        monthly = self.load_monthly_trend()
        market = self.load_market_share_trend()
        city = self.load_city_performance()
        quarter = self.load_active_quarter()
        recent = self.load_recent_uploads()
        ai_scores = self.load_ai_scores(recovery, overall)

        return {
            **counts,
            **last_upload,
            **recovery,
            **overall,
            **product_perf,
            **top_reps,
            **monthly,
            **market,
            **city,
            **quarter,
            **recent,
            **ai_scores,
            "prime_summary": self.load_prime_summary(),
            "quarter_summary": self.load_quarter_summary(),
            "ai_messages": self.build_ai_messages(recovery),
        }

    @classmethod
    def health(cls):
        return {"service": "DashboardService", "status": "READY", "version": "3.0.0"}
