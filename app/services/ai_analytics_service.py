"""
AI Analytics Service
====================
Enterprise AI karar destek servisi.
Gerçek IMS verisinden risk, fırsat, prim ve tahmin hesaplar.

Tüm metodlar hata dayanıklıdır: eksik veri varsa sistem çökmez,
bilgilendirici mesaj döner. Sonuçlar 5 dakika cache edilir.
"""

import logging
import time
from datetime import date

from sqlalchemy import func

from app.extensions import db
from app.models import (
    IMSSummary,
    Product,
    RecoverySummary,
    Representative,
    Target,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Basit in-memory cache (5 dakika TTL, harici bağımlılık gerektirmez)
# ---------------------------------------------------------------------------
_CACHE: dict = {}
CACHE_TTL = 300  # saniye


def _cache_get(key):
    """Cache'ten değer al. (değer, hit:bool) tuple döner."""
    entry = _CACHE.get(key)
    if entry:
        value, expires_at = entry
        if time.time() < expires_at:
            return value, True
    return None, False


def _cache_set(key, value):
    """Değeri cache'e yaz."""
    _CACHE[key] = (value, time.time() + CACHE_TTL)


def _cache_clear():
    """Tüm cache'i temizle (test için)."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Yardımcı toplu sorgu yükleyiciler (N+1 önleme)
# ---------------------------------------------------------------------------

def _load_product_actuals() -> dict:
    """product_id → toplam TL gerçekleşme (tek sorgu)."""
    rows = (
        db.session.query(IMSSummary.product_id, func.sum(IMSSummary.tl))
        .group_by(IMSSummary.product_id)
        .all()
    )
    return {pid: (tl or 0) for pid, tl in rows}


def _load_product_targets() -> dict:
    """product_id → toplam TL hedef (tek sorgu)."""
    rows = (
        db.session.query(Target.product_id, func.sum(Target.tl_target))
        .group_by(Target.product_id)
        .all()
    )
    return {pid: (tl or 0) for pid, tl in rows}


def _load_product_growth() -> dict:
    """product_id → ortalama büyüme (tek sorgu)."""
    rows = (
        db.session.query(IMSSummary.product_id, func.avg(IMSSummary.growth))
        .group_by(IMSSummary.product_id)
        .all()
    )
    return {pid: (g or 0) for pid, g in rows}


def _load_product_market_share() -> dict:
    """product_id → ortalama pazar payı (tek sorgu)."""
    rows = (
        db.session.query(IMSSummary.product_id, func.avg(IMSSummary.market_share))
        .group_by(IMSSummary.product_id)
        .all()
    )
    return {pid: (s or 0) for pid, s in rows}


def _load_rep_actuals() -> dict:
    """representative_id → toplam TL gerçekleşme (tek sorgu)."""
    rows = (
        db.session.query(IMSSummary.representative_id, func.sum(IMSSummary.tl))
        .group_by(IMSSummary.representative_id)
        .all()
    )
    return {rid: (tl or 0) for rid, tl in rows}


def _load_rep_targets() -> dict:
    """representative_id → toplam TL hedef (tek sorgu)."""
    rows = (
        db.session.query(Target.representative_id, func.sum(Target.tl_target))
        .group_by(Target.representative_id)
        .all()
    )
    return {rid: (tl or 0) for rid, tl in rows}


def _load_recovery_by_product() -> dict:
    """product_id → RecoverySummary (ilk kayıt, tek sorgu)."""
    rows = RecoverySummary.query.all()
    result = {}
    for r in rows:
        if r.product_id and r.product_id not in result:
            result[r.product_id] = r
    return result


# ---------------------------------------------------------------------------
# AIAnalyticsService
# ---------------------------------------------------------------------------

class AIAnalyticsService:
    """
    Dashboard için gerçek zamanlı AI hesaplama servisi.
    Tüm public metodlar hata dayanıklıdır.
    """

    # ------------------------------------------------------------------
    # 1) Risk Score
    # ------------------------------------------------------------------
    def calculate_risk_score(self) -> int:
        """
        0-100 arası risk puanı.
        Yüksek puan = yüksek risk.

        Kriterler:
        - Hedef altı gerçekleşme (<%70: +40, <%85: +20, <%100: +10)
        - Kritik/Riskli recovery durumu (+30/+20/+10)
        - Negatif büyüme trendi (<%−5: +20, <0: +10)
        - Düşük pazar payı (<%5: +10)
        """
        t0 = time.time()
        try:
            products = Product.query.filter_by(is_active=True).all()
            total = len(products)
            if total == 0:
                return 0

            actuals = _load_product_actuals()
            targets = _load_product_targets()
            growth = _load_product_growth()
            shares = _load_product_market_share()
            recovery_map = _load_recovery_by_product()

            risk_points = 0
            evaluated = 0

            for p in products:
                tl = actuals.get(p.id, 0)
                tgt = targets.get(p.id, 0)
                if tgt <= 0:
                    continue  # hedef tanımsız → değerlendirme dışı
                evaluated += 1
                pct = (tl / tgt * 100)
                g = growth.get(p.id, 0)
                s = shares.get(p.id, 0)
                rec = recovery_map.get(p.id)

                # Gerçekleşme
                if pct < 70:
                    risk_points += 40
                elif pct < 85:
                    risk_points += 20
                elif pct < 100:
                    risk_points += 10

                # Recovery
                if rec:
                    if rec.status == "Kritik":
                        risk_points += 30
                    elif rec.status == "Riskli":
                        risk_points += 20
                    elif rec.status == "Takip":
                        risk_points += 10

                # Trend
                if g < -5:
                    risk_points += 20
                elif g < 0:
                    risk_points += 10

                # Pazar payı
                if s < 5:
                    risk_points += 10

            score = round(min(100, risk_points / (evaluated * 100) * 100)) if evaluated > 0 else 0
        except Exception as exc:
            logger.error("[AIAnalytics] calculate_risk_score hata: %s", exc)
            score = 0

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] calculate_risk_score=%d (%dms)", score, elapsed)
        return score

    # ------------------------------------------------------------------
    # 2) Opportunity Score
    # ------------------------------------------------------------------
    def calculate_opportunity_score(self) -> int:
        """
        0-100 arası fırsat puanı.
        Kriterler:
        - Hedefe yakın ürünler (80-100%: +30, ≥100%: +50)
        - Recovery potansiyeli (+20)
        - Yükselen trend (>%10: +20, >0: +10)
        - Yüksek pazar payı (>%20: +10)
        """
        t0 = time.time()
        try:
            products = Product.query.filter_by(is_active=True).all()
            total = len(products)
            if total == 0:
                return 0

            actuals = _load_product_actuals()
            targets = _load_product_targets()
            growth = _load_product_growth()
            shares = _load_product_market_share()
            recovery_map = _load_recovery_by_product()

            opp_points = 0
            evaluated = 0

            for p in products:
                tgt = targets.get(p.id, 0)
                if tgt <= 0:
                    continue  # hedef tanımsız → değerlendirme dışı
                evaluated += 1
                tl = actuals.get(p.id, 0)
                pct = (tl / tgt * 100)
                g = growth.get(p.id, 0)
                s = shares.get(p.id, 0)
                rec = recovery_map.get(p.id)

                if pct >= 100:
                    opp_points += 50
                elif pct >= 80:
                    opp_points += 30

                if rec and rec.remaining_tl > 0:
                    opp_points += 20

                if g > 10:
                    opp_points += 20
                elif g > 0:
                    opp_points += 10

                if s > 20:
                    opp_points += 10

            score = round(min(100, opp_points / (evaluated * 100) * 100)) if evaluated > 0 else 0
        except Exception as exc:
            logger.error("[AIAnalytics] calculate_opportunity_score hata: %s", exc)
            score = 0

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] calculate_opportunity_score=%d (%dms)", score, elapsed)
        return score

    # ------------------------------------------------------------------
    # 3) Goal Probability
    # ------------------------------------------------------------------
    def calculate_goal_probability(self) -> float:
        """
        Bu ay hedefe ulaşma olasılığı (0-100).
        Değişkenler: mevcut gerçekleşme, ayın günü, günlük hız projeksiyonu, recovery.
        """
        t0 = time.time()
        try:
            today = date.today()
            days_in_month = 30
            day_of_month = max(today.day, 1)
            days_remaining = max(0, days_in_month - day_of_month)

            total_tl = db.session.query(func.sum(IMSSummary.tl)).scalar() or 0
            target_tl = db.session.query(func.sum(Target.tl_target)).scalar() or 0

            if target_tl <= 0:
                probability = 0.0
            else:
                daily_rate = total_tl / day_of_month
                projected = total_tl + (daily_rate * days_remaining)
                projected_pct = projected / target_tl * 100

                recovery_tl = db.session.query(func.sum(RecoverySummary.remaining_tl)).scalar() or 0
                recovery_boost = min(10.0, (recovery_tl / target_tl * 100)) if recovery_tl > 0 else 0.0

                probability = round(min(100.0, projected_pct + recovery_boost), 1)
        except Exception as exc:
            logger.error("[AIAnalytics] calculate_goal_probability hata: %s", exc)
            probability = 0.0

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] calculate_goal_probability=%%%.1f (%dms)", probability, elapsed)
        return probability

    # ------------------------------------------------------------------
    # 4) Expected Prime
    # ------------------------------------------------------------------
    def calculate_expected_prime(self) -> dict:
        """
        Prim motorundan türetilmiş tahminler.
        Döner: expected_prime, max_prime, lost_prime, recovery_prime.
        """
        t0 = time.time()
        try:
            total_tl = db.session.query(func.sum(IMSSummary.tl)).scalar() or 0
            target_tl = db.session.query(func.sum(Target.tl_target)).scalar() or 0
            total_bonus = db.session.query(func.sum(IMSSummary.bonus_amount)).scalar() or 0

            lost = max(0.0, target_tl - total_tl)
            recovery_tl = db.session.query(func.sum(RecoverySummary.remaining_tl)).scalar() or 0
            recovery_prime = total_bonus * 0.10 if recovery_tl > 0 else 0.0

            result = {
                "expected_prime": round(total_bonus, 0),
                "max_prime": round(total_bonus * 1.15, 0),
                "lost_prime": round(lost, 0),
                "recovery_prime": round(total_bonus + recovery_prime, 0),
            }
        except Exception as exc:
            logger.error("[AIAnalytics] calculate_expected_prime hata: %s", exc)
            result = {"expected_prime": 0, "max_prime": 0, "lost_prime": 0, "recovery_prime": 0}

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] calculate_expected_prime (%dms)", elapsed)
        return result

    # ------------------------------------------------------------------
    # 5) Lost Prime (kısayol)
    # ------------------------------------------------------------------
    def calculate_lost_prime(self) -> float:
        """Hedef ile gerçekleşme arasındaki TL farkı (kaçırılan prim tabanı)."""
        t0 = time.time()
        try:
            total_tl = db.session.query(func.sum(IMSSummary.tl)).scalar() or 0
            target_tl = db.session.query(func.sum(Target.tl_target)).scalar() or 0
            lost = round(max(0.0, target_tl - total_tl), 0)
        except Exception as exc:
            logger.error("[AIAnalytics] calculate_lost_prime hata: %s", exc)
            lost = 0.0
        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] calculate_lost_prime=%.0f (%dms)", lost, elapsed)
        return lost

    # ------------------------------------------------------------------
    # 6) Predict Next Month
    # ------------------------------------------------------------------
    def predict_next_month(self) -> dict:
        """
        Son 3 aylık trend üzerinden gelecek ay tahmini.
        Döner: predicted_tl, trend_direction (up/down/stable), confidence.
        """
        t0 = time.time()
        try:
            rows = (
                db.session.query(
                    IMSSummary.year,
                    IMSSummary.month,
                    func.sum(IMSSummary.tl).label("total_tl"),
                )
                .group_by(IMSSummary.year, IMSSummary.month)
                .order_by(IMSSummary.year.desc(), IMSSummary.month.desc())
                .limit(3)
                .all()
            )

            if not rows:
                result = {"predicted_tl": 0, "trend_direction": "stable", "confidence": 0}
            elif len(rows) == 1:
                current = rows[0].total_tl or 0
                result = {
                    "predicted_tl": round(current * 1.05, 0),
                    "trend_direction": "stable",
                    "confidence": 40,
                }
            else:
                values = list(reversed([r.total_tl or 0 for r in rows]))
                growth = (values[-1] - values[0]) / max(len(values) - 1, 1)
                predicted = max(0.0, values[-1] + growth)
                last = values[-1] or 1
                if growth > last * 0.02:
                    direction = "up"
                elif growth < -last * 0.02:
                    direction = "down"
                else:
                    direction = "stable"
                confidence = min(85, 50 + round(abs(growth / last) * 100))
                result = {
                    "predicted_tl": round(predicted, 0),
                    "trend_direction": direction,
                    "confidence": confidence,
                }
        except Exception as exc:
            logger.error("[AIAnalytics] predict_next_month hata: %s", exc)
            result = {"predicted_tl": 0, "trend_direction": "stable", "confidence": 0}

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] predict_next_month=%s (%dms)", result.get("trend_direction"), elapsed)
        return result

    # ------------------------------------------------------------------
    # 7) Generate Daily Summary
    # ------------------------------------------------------------------
    def generate_daily_summary(self) -> list:
        """
        Bugünün otomatik özet mesajları.
        Örn: 'Travazol hedefe çok yakın.', '3 temsilci hedef altında.'
        """
        t0 = time.time()
        messages = []
        try:
            risky = self.detect_risky_products()
            near = self.detect_products_close_to_target()
            risky_reps = self.detect_risky_representatives()
            goal_prob = self.calculate_goal_probability()

            if not risky:
                messages.append("Bugün riskli ürün bulunmadı.")
            else:
                messages.append(f"{len(risky)} ürün risk altında takip edilmeli.")

            for p in near[:2]:
                messages.append(
                    f"{p['product_name']} hedefe çok yakın (%{p['realization_percent']})."
                )

            recovery_count = RecoverySummary.query.filter(
                RecoverySummary.status.in_(["Kritik", "Riskli"])
            ).count()
            if recovery_count > 0:
                messages.append(f"{recovery_count} ürün Recovery gerekiyor.")

            if risky_reps:
                messages.append(f"{len(risky_reps)} temsilci hedef altında.")

            if goal_prob > 0:
                messages.append(f"Bu ay hedefe ulaşma olasılığı %{goal_prob}.")
        except Exception as exc:
            logger.error("[AIAnalytics] generate_daily_summary hata: %s", exc)
            messages = ["Günlük özet hesaplanamadı."]

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] generate_daily_summary=%d mesaj (%dms)", len(messages), elapsed)
        return messages

    # ------------------------------------------------------------------
    # 8) Detect Risky Products
    # ------------------------------------------------------------------
    def detect_risky_products(self) -> list:
        """
        Riskli ürünleri bul.
        Kriter: gerçekleşme <%70 veya Kritik/Riskli recovery veya negatif trend.
        Her ürün: product_name, realization_percent, risk_reasons listesi.
        """
        t0 = time.time()
        risky = []
        try:
            products = Product.query.filter_by(is_active=True).all()
            actuals = _load_product_actuals()
            targets = _load_product_targets()
            growth = _load_product_growth()
            recovery_map = _load_recovery_by_product()

            for p in products:
                tgt = targets.get(p.id, 0)
                tl = actuals.get(p.id, 0)
                g = growth.get(p.id, 0)
                rec = recovery_map.get(p.id)
                has_recovery = rec and rec.status in ("Kritik", "Riskli")

                reasons = []
                if tgt > 0:
                    pct = tl / tgt * 100
                    if pct < 70:
                        reasons.append("Düşük gerçekleşme")
                else:
                    pct = 0.0

                if has_recovery:
                    reasons.append(f"Recovery ({rec.status})")
                if g < -5:
                    reasons.append("Negatif trend")

                if reasons:
                    risky.append({
                        "product_name": p.product_name,
                        "realization_percent": round(pct, 1),
                        "has_recovery": bool(has_recovery),
                        "avg_growth": round(g, 1),
                        "risk_reasons": reasons,
                    })

            risky.sort(key=lambda x: x["realization_percent"])
        except Exception as exc:
            logger.error("[AIAnalytics] detect_risky_products hata: %s", exc)
            risky = []

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] detect_risky_products=%d ürün (%dms)", len(risky), elapsed)
        return risky

    # ------------------------------------------------------------------
    # 9) Detect Risky Representatives
    # ------------------------------------------------------------------
    def detect_risky_representatives(self) -> list:
        """
        Gerçekleşmesi <%70 olan temsilciler.
        Her kayıt: rep_name, city, realization_percent, risk_score, missing_tl.
        """
        t0 = time.time()
        risky = []
        try:
            reps = Representative.query.filter_by(active=True).all()
            actuals = _load_rep_actuals()
            rep_targets = _load_rep_targets()

            for rep in reps:
                tgt = rep_targets.get(rep.id, 0)
                if tgt <= 0:
                    continue
                tl = actuals.get(rep.id, 0)
                pct = tl / tgt * 100
                if pct < 70:
                    risky.append({
                        "rep_name": rep.rep_name,
                        "city": rep.city or "-",
                        "realization_percent": round(pct, 1),
                        "risk_score": round(100 - pct),
                        "missing_tl": round(max(0.0, tgt - tl), 0),
                    })

            risky.sort(key=lambda x: x["realization_percent"])
        except Exception as exc:
            logger.error("[AIAnalytics] detect_risky_representatives hata: %s", exc)
            risky = []

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] detect_risky_representatives=%d temsilci (%dms)", len(risky), elapsed)
        return risky

    # ------------------------------------------------------------------
    # 10) Products Close to Target
    # ------------------------------------------------------------------
    def detect_products_close_to_target(self) -> list:
        """
        Hedefe yakın ürünler (80-99.9%).
        Her kayıt: product_name, realization_percent, missing_tl.
        """
        t0 = time.time()
        near = []
        try:
            products = Product.query.filter_by(is_active=True).all()
            actuals = _load_product_actuals()
            targets = _load_product_targets()

            for p in products:
                tgt = targets.get(p.id, 0)
                if tgt <= 0:
                    continue
                tl = actuals.get(p.id, 0)
                pct = tl / tgt * 100
                if 80.0 <= pct < 100.0:
                    near.append({
                        "product_name": p.product_name,
                        "realization_percent": round(pct, 1),
                        "missing_tl": round(max(0.0, tgt - tl), 0),
                    })

            near.sort(key=lambda x: x["realization_percent"], reverse=True)
        except Exception as exc:
            logger.error("[AIAnalytics] detect_products_close_to_target hata: %s", exc)
            near = []

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] detect_products_close_to_target=%d ürün (%dms)", len(near), elapsed)
        return near

    # ------------------------------------------------------------------
    # 11) Action Recommendations
    # ------------------------------------------------------------------
    def generate_action_recommendations(self) -> list:
        """
        AI tabanlı aksiyon önerileri.
        Her öneri: icon, type, text.
        """
        t0 = time.time()
        actions = []
        try:
            near = self.detect_products_close_to_target()
            for p in near[:3]:
                actions.append({
                    "icon": "bi-arrow-up-circle-fill",
                    "type": "opportunity",
                    "text": (
                        f"{p['product_name']} için ek ziyaret planlayın "
                        f"(%{p['realization_percent']} gerçekleşme, "
                        f"{int(p['missing_tl']):,} ₺ kaldı)."
                    ),
                })

            recovery_rows = (
                RecoverySummary.query.filter(
                    RecoverySummary.status.in_(["Kritik", "Riskli"])
                )
                .all()
            )
            seen_products = set()
            for r in recovery_rows:
                if r.product_id in seen_products:
                    continue
                seen_products.add(r.product_id)
                name = r.product.product_name if r.product else "Ürün"
                actions.append({
                    "icon": "bi-arrow-clockwise",
                    "type": "recovery",
                    "text": f"{name} Recovery çalışması başlatın.",
                })

            risky_reps = self.detect_risky_representatives()
            for rep in risky_reps[:2]:
                actions.append({
                    "icon": "bi-person-fill-exclamation",
                    "type": "support",
                    "text": (
                        f"{rep['rep_name']} için destek planlayın "
                        f"(%{rep['realization_percent']} gerçekleşme)."
                    ),
                })

            if not actions:
                actions.append({
                    "icon": "bi-check2-all",
                    "type": "ok",
                    "text": "Acil aksiyon gerektiren durum bulunmuyor.",
                })
        except Exception as exc:
            logger.error("[AIAnalytics] generate_action_recommendations hata: %s", exc)
            actions = [{"icon": "bi-info-circle", "type": "info", "text": "Öneri hesaplanamadı."}]

        elapsed = int((time.time() - t0) * 1000)
        logger.info(
            "[AIAnalytics] generate_action_recommendations=%d öneri (%dms)", len(actions), elapsed
        )
        return actions

    # ------------------------------------------------------------------
    # 12) Management Summary
    # ------------------------------------------------------------------
    def generate_management_summary(self) -> dict:
        """
        Yönetici özeti:
        overall_percent, critical_product, best_representative,
        risky_city, expected_prime, recovery_opportunity_tl, next_month_prediction.
        """
        t0 = time.time()
        summary = {}
        try:
            total_tl = db.session.query(func.sum(IMSSummary.tl)).scalar() or 0
            target_tl = db.session.query(func.sum(Target.tl_target)).scalar() or 0
            overall_pct = round(total_tl / target_tl * 100, 1) if target_tl > 0 else 0.0

            risky = self.detect_risky_products()
            critical_product = risky[0]["product_name"] if risky else None

            reps = Representative.query.filter_by(active=True).all()
            actuals = _load_rep_actuals()
            rep_targets = _load_rep_targets()
            best_rep = None
            best_pct = -1.0
            for rep in reps:
                tgt = rep_targets.get(rep.id, 0)
                if tgt <= 0:
                    continue
                pct = actuals.get(rep.id, 0) / tgt * 100
                if pct > best_pct:
                    best_pct = pct
                    best_rep = {
                        "name": rep.rep_name,
                        "city": rep.city or "-",
                        "percent": round(pct, 1),
                    }

            risky_reps = self.detect_risky_representatives()
            risky_city = risky_reps[0]["city"] if risky_reps else None

            prime_data = self.calculate_expected_prime()
            recovery_tl = db.session.query(func.sum(RecoverySummary.remaining_tl)).scalar() or 0
            prediction = self.predict_next_month()

            summary = {
                "overall_percent": overall_pct,
                "overall_tl": round(total_tl, 0),
                "target_tl": round(target_tl, 0),
                "critical_product": critical_product,
                "best_representative": best_rep,
                "risky_city": risky_city,
                "expected_prime": prime_data["expected_prime"],
                "recovery_opportunity_tl": round(recovery_tl, 0),
                "next_month_prediction": prediction,
            }
        except Exception as exc:
            logger.error("[AIAnalytics] generate_management_summary hata: %s", exc)
            summary = {}

        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] generate_management_summary (%dms)", elapsed)
        return summary

    # ------------------------------------------------------------------
    # Toplu çalıştırma (cache destekli)
    # ------------------------------------------------------------------
    def run_all(self) -> dict:
        """
        Tüm AI hesaplamalarını çalıştır ve sonuçları döndür.
        Sonuçlar 5 dakika cache edilir.
        """
        cached, hit = _cache_get("ai_analytics_all")
        if hit:
            logger.info("[AIAnalytics] Cache hit: run_all")
            return cached

        t0 = time.time()
        logger.info("[AIAnalytics] Cache miss: run_all hesaplanıyor...")

        try:
            risk_score = self.calculate_risk_score()
            opportunity_score = self.calculate_opportunity_score()
            goal_probability = self.calculate_goal_probability()
            prime_data = self.calculate_expected_prime()
            next_month = self.predict_next_month()
            daily_summary = self.generate_daily_summary()
            risky_products = self.detect_risky_products()
            risky_reps = self.detect_risky_representatives()
            near_target = self.detect_products_close_to_target()
            recommendations = self.generate_action_recommendations()
            mgmt_summary = self.generate_management_summary()

            result = {
                "risk_score": risk_score,
                "opportunity_score": opportunity_score,
                "goal_probability": goal_probability,
                "expected_prime": prime_data["expected_prime"],
                "max_prime": prime_data["max_prime"],
                "lost_prime": prime_data["lost_prime"],
                "recovery_prime": prime_data["recovery_prime"],
                "next_month": next_month,
                "daily_summary": daily_summary,
                "risky_products": risky_products,
                "risky_representatives": risky_reps,
                "products_close_to_target": near_target,
                "action_recommendations": recommendations,
                "management_summary": mgmt_summary,
            }
        except Exception as exc:
            logger.error("[AIAnalytics] run_all hata: %s", exc)
            result = _empty_result()

        _cache_set("ai_analytics_all", result)
        elapsed = int((time.time() - t0) * 1000)
        logger.info("[AIAnalytics] run_all tamamlandı (%dms)", elapsed)
        return result


def _empty_result() -> dict:
    """Hata durumunda güvenli boş sonuç seti."""
    return {
        "risk_score": 0,
        "opportunity_score": 0,
        "goal_probability": 0.0,
        "expected_prime": 0,
        "max_prime": 0,
        "lost_prime": 0,
        "recovery_prime": 0,
        "next_month": {"predicted_tl": 0, "trend_direction": "stable", "confidence": 0},
        "daily_summary": ["Veri henüz yüklenmedi."],
        "risky_products": [],
        "risky_representatives": [],
        "products_close_to_target": [],
        "action_recommendations": [
            {"icon": "bi-upload", "type": "info", "text": "IMS dosyası yükleyin."}
        ],
        "management_summary": {},
    }
