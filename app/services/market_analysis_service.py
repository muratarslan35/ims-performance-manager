"""Manager-facing Türkiye market analysis with explicit IMS week provenance.

The dashboard itself should stay compact. This service owns only the dedicated
Türkiye Pazar Analizi read model. It resolves the newest completed IMS upload for
the selected month, uses its competition rows when present, otherwise falls back
to the newest earlier week in the same month that contains real competition TL
rows. If the month has no competition rows at all, company IMS values from the
latest completed upload are still returned so the screen never becomes a blank
or misleading zero-market table.

Every company product is emitted at most once. Duplicate/legacy competition group
labels are collapsed onto the canonical Product row and the strongest real market
row (largest positive TL market) is selected; rows are never summed across two
aliases of the same company product.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Optional

from sqlalchemy import case, desc, func

from app.extensions import db
from app.models import CompetitionData, IMSSummary, IMSUpload, Product


class MarketAnalysisService:
    """Build a simple, source-transparent national competition read model."""

    SOURCE_CURRENT = "CURRENT"
    SOURCE_FALLBACK = "FALLBACK"
    SOURCE_IMS_ONLY = "IMS_ONLY"

    def __init__(self, year: int, month: int, session=None):
        self.year = int(year)
        self.month = int(month)
        self.session = session or db.session

    @staticmethod
    def _key(value) -> str:
        return "".join(ch for ch in str(value or "").upper() if ch.isalnum())

    def _completed_uploads(self):
        return (
            self.session.query(IMSUpload)
            .filter(
                IMSUpload.year == self.year,
                IMSUpload.month == self.month,
                IMSUpload.status == "COMPLETED",
            )
            .order_by(
                desc(IMSUpload.week_number),
                desc(IMSUpload.completed_at),
                desc(IMSUpload.id),
            )
            .all()
        )

    def _has_real_competition(self, upload_id: int) -> bool:
        return bool(
            self.session.query(CompetitionData.id)
            .filter(
                CompetitionData.upload_id == int(upload_id),
                CompetitionData.metric_type == "TL",
                CompetitionData.metric_value != 0,
                CompetitionData.is_subtotal.is_(False),
                CompetitionData.is_grand_total.is_(False),
            )
            .limit(1)
            .scalar()
        )

    def _resolve_source(self):
        uploads = self._completed_uploads()
        latest = uploads[0] if uploads else None
        competition_upload = next(
            (upload for upload in uploads if self._has_real_competition(upload.id)),
            None,
        )
        if latest is None:
            return None, None, self.SOURCE_IMS_ONLY
        if competition_upload is None:
            return latest, latest, self.SOURCE_IMS_ONLY
        if int(competition_upload.id) == int(latest.id):
            return latest, competition_upload, self.SOURCE_CURRENT
        return latest, competition_upload, self.SOURCE_FALLBACK

    def _competition_groups(self, upload_id: Optional[int]):
        if not upload_id:
            return []
        return (
            self.session.query(
                CompetitionData.product_group.label("product_group"),
                func.coalesce(
                    func.sum(
                        case(
                            (CompetitionData.metric_type == "TL", CompetitionData.metric_value),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ).label("market_tl"),
                func.avg(
                    case(
                        (CompetitionData.metric_type == "MARKET_SHARE", CompetitionData.metric_value),
                        else_=None,
                    )
                ).label("market_share"),
            )
            .filter(
                CompetitionData.upload_id == int(upload_id),
                CompetitionData.is_subtotal.is_(False),
                CompetitionData.is_grand_total.is_(False),
                CompetitionData.metric_type.in_(("TL", "MARKET_SHARE")),
            )
            .group_by(CompetitionData.product_group)
            .all()
        )

    def _company_tl_by_product(self, upload_id: Optional[int]) -> Dict[int, float]:
        if not upload_id:
            return {}
        rows = (
            self.session.query(
                IMSSummary.product_id,
                func.coalesce(func.sum(IMSSummary.tl), 0.0),
            )
            .filter(IMSSummary.upload_id == int(upload_id))
            .group_by(IMSSummary.product_id)
            .all()
        )
        return {int(product_id): float(value or 0.0) for product_id, value in rows if product_id is not None}

    @staticmethod
    def _product_aliases(product: Product) -> Iterable[str]:
        for value in (product.product_name, product.product_code, getattr(product, "ims_name", None)):
            key = MarketAnalysisService._key(value)
            if key:
                yield key

    def _match_candidates(self, product: Product, groups):
        aliases = tuple(self._product_aliases(product))
        matched = []
        for row in groups:
            group_key = self._key(getattr(row, "product_group", ""))
            if any(alias in group_key or group_key in alias for alias in aliases):
                matched.append(row)
        return matched

    @staticmethod
    def _choose_market_row(candidates):
        if not candidates:
            return None
        # Duplicate aliases must never be added together. Prefer an actually
        # populated TL market; when more than one alias is populated, the
        # broader/larger market row is the safest non-duplicating source.
        return max(
            candidates,
            key=lambda row: (
                float(getattr(row, "market_tl", 0.0) or 0.0) > 0,
                float(getattr(row, "market_tl", 0.0) or 0.0),
                float(getattr(row, "market_share", 0.0) or 0.0),
            ),
        )

    @staticmethod
    def _week(upload) -> Optional[int]:
        value = getattr(upload, "week_number", None) if upload is not None else None
        return int(value) if value is not None else None

    def _source_message(self, state, latest, source) -> str:
        latest_week = self._week(latest)
        source_week = self._week(source)
        if state == self.SOURCE_CURRENT:
            return (
                f"Veriler güncel {source_week}. hafta IMS dosyasından alınmıştır. "
                "Rekabet ve şirket IMS değerleri aynı haftaya aittir."
            ) if source_week else "Veriler güncel IMS dosyasından alınmıştır."
        if state == self.SOURCE_FALLBACK:
            return (
                f"{latest_week}. hafta IMS verisinde rakip analizi mevcut değil. "
                f"Tablodaki rekabet ve şirket IMS verileri son kullanılabilir kaynak olan {source_week}. hafta IMS dosyasına aittir."
            )
        if latest_week:
            return (
                f"{latest_week}. hafta IMS verisinde rakip analizi mevcut değil ve bu ay için daha eski kullanılabilir "
                f"rekabet verisi bulunamadı. Şirket IMS verileri {latest_week}. hafta dosyasından gösteriliyor; "
                "rakip ve toplam pazar alanları veri gelene kadar boş bırakılır."
            )
        return "Seçili ay için tamamlanmış IMS veya rekabet verisi bulunmuyor."

    def build(self) -> dict:
        latest, source, state = self._resolve_source()
        data_upload = source if source is not None else latest
        competition_rows = self._competition_groups(source.id if source and state != self.SOURCE_IMS_ONLY else None)
        company_by_product = self._company_tl_by_product(data_upload.id if data_upload else None)

        products = (
            self.session.query(Product)
            .filter(Product.is_active.is_(True))
            .order_by(Product.display_order.asc(), Product.product_name.asc())
            .all()
        )

        groups = []
        market_total = 0.0
        company_market_total = 0.0
        company_total = 0.0
        for product in products:
            company_tl = float(company_by_product.get(int(product.id), 0.0) or 0.0)
            selected = self._choose_market_row(self._match_candidates(product, competition_rows))
            market_available = selected is not None and float(getattr(selected, "market_tl", 0.0) or 0.0) > 0
            market_tl = float(getattr(selected, "market_tl", 0.0) or 0.0) if market_available else None
            reported_share = float(getattr(selected, "market_share", 0.0) or 0.0) if selected is not None else None
            competitor_tl = max(float(market_tl) - company_tl, 0.0) if market_available else None
            company_share = round(company_tl * 100.0 / float(market_tl), 2) if market_available and market_tl else None

            company_total += company_tl
            if market_available:
                market_total += float(market_tl)
                company_market_total += company_tl

            groups.append(
                {
                    "product_id": int(product.id),
                    "company_product": product.product_name,
                    "product_group": getattr(selected, "product_group", None) if selected is not None else None,
                    "company_sales_tl": round(company_tl, 2),
                    "market_sales_tl": round(float(market_tl), 2) if market_tl is not None else None,
                    "competitor_sales_tl": round(float(competitor_tl), 2) if competitor_tl is not None else None,
                    "company_share_percent": company_share,
                    "reported_market_share_percent": round(reported_share, 2) if reported_share is not None else None,
                    "market_available": bool(market_available),
                    "data_status": "REKABET + IMS" if market_available else "YALNIZ IMS",
                }
            )

        competitor_total = max(market_total - company_market_total, 0.0)
        source_week = self._week(source)
        latest_week = self._week(latest)
        return {
            "year": self.year,
            "month": self.month,
            "latest_week": latest_week,
            "source_week": source_week,
            "source_state": state,
            "is_current": state == self.SOURCE_CURRENT,
            "is_fallback": state == self.SOURCE_FALLBACK,
            "has_competition": state != self.SOURCE_IMS_ONLY and bool(competition_rows),
            "source_message": self._source_message(state, latest, source),
            "source_file": getattr(data_upload, "file_name", None) if data_upload is not None else None,
            "market_total_tl": round(market_total, 2),
            "company_total_tl": round(company_total, 2),
            "competitor_total_tl": round(competitor_total, 2),
            "company_share_percent": round(company_market_total * 100.0 / market_total, 2) if market_total else 0.0,
            "groups": groups,
        }
