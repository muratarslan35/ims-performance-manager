"""Manager-facing Türkiye market analysis with explicit IMS week provenance.

The dashboard itself should stay compact. This service owns only the dedicated
Türkiye Pazar Analizi read model. It resolves the newest completed IMS upload for
the selected month and uses the newest real competition source from that month.

Legacy workbooks can provide TL competition directly. New KPI-style workbooks
provide authoritative product/competitor KUTU observations instead. The read
model must never call those rows "missing" merely because TL competition is not
present. TL is preferred when available; otherwise the screen switches openly to
KUTU mode. No synthetic TL market value is fabricated from box counts.

Every company product is emitted at most once. Duplicate/legacy competition group
labels are collapsed onto the canonical Product row and the strongest real market
row is selected; rows are never summed across two aliases of the same company
product.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, Iterable, Optional

from sqlalchemy import case, desc, func

from app.extensions import db
from app.models import CompetitionData, IMSFact, IMSRawData, IMSSummary, IMSUpload, Product


class MarketAnalysisService:
    """Build a simple, source-transparent national competition read model."""

    SOURCE_CURRENT = "CURRENT"
    SOURCE_FALLBACK = "FALLBACK"
    SOURCE_IMS_ONLY = "IMS_ONLY"

    METRIC_TL = "TL"
    METRIC_UNIT = "UNIT"

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

    def _competition_metric(self, upload_id: int) -> Optional[str]:
        """Prefer real TL competition; fall back to authoritative KUTU rows."""
        for metric in (self.METRIC_TL, self.METRIC_UNIT):
            exists = (
                self.session.query(CompetitionData.id)
                .filter(
                    CompetitionData.upload_id == int(upload_id),
                    CompetitionData.metric_type == metric,
                    CompetitionData.metric_value != 0,
                    CompetitionData.is_grand_total.is_(False),
                )
                .limit(1)
                .scalar()
            )
            if exists:
                return metric
        return None

    def _has_real_competition(self, upload_id: int) -> bool:
        return self._competition_metric(upload_id) is not None

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

    def _competition_groups_tl(self, upload_id: int):
        return (
            self.session.query(
                CompetitionData.product_group.label("product_group"),
                func.coalesce(
                    func.sum(
                        case(
                            (CompetitionData.metric_type == self.METRIC_TL, CompetitionData.metric_value),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ).label("market_value"),
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
                CompetitionData.metric_type.in_((self.METRIC_TL, "MARKET_SHARE")),
            )
            .group_by(CompetitionData.product_group)
            .all()
        )

    def _competition_groups_unit(self, upload_id: int):
        """Use PAZAR/subtotal KUTU as authority, with detail sum as safe fallback."""
        rows = (
            self.session.query(
                CompetitionData.product_group,
                CompetitionData.metric_value,
                CompetitionData.is_subtotal,
            )
            .filter(
                CompetitionData.upload_id == int(upload_id),
                CompetitionData.metric_type == self.METRIC_UNIT,
                CompetitionData.is_grand_total.is_(False),
            )
            .all()
        )
        buckets = {}
        for group, value, is_subtotal in rows:
            key = str(group or "").strip()
            if not key:
                continue
            bucket = buckets.setdefault(key, {"subtotal": 0.0, "detail": 0.0})
            if bool(is_subtotal):
                bucket["subtotal"] += float(value or 0.0)
            else:
                bucket["detail"] += float(value or 0.0)

        result = []
        for group, values in buckets.items():
            market_value = values["subtotal"] if values["subtotal"] > 0 else values["detail"]
            if market_value <= 0:
                continue
            result.append(
                SimpleNamespace(
                    product_group=group,
                    market_value=market_value,
                    market_share=None,
                )
            )
        return result

    def _competition_groups(self, upload_id: Optional[int], metric_mode: Optional[str]):
        if not upload_id or metric_mode not in {self.METRIC_TL, self.METRIC_UNIT}:
            return []
        if metric_mode == self.METRIC_UNIT:
            return self._competition_groups_unit(int(upload_id))
        return self._competition_groups_tl(int(upload_id))

    def _company_metric_by_product(self, upload_id: Optional[int], metric_mode: str) -> Dict[int, float]:
        """Read the exact upload's official NATIONAL company metric when available."""
        if not upload_id:
            return {}

        official_column = IMSRawData.unit if metric_mode == self.METRIC_UNIT else IMSRawData.tl
        official_rows = (
            self.session.query(
                IMSRawData.product_id,
                func.coalesce(func.sum(official_column), 0.0),
            )
            .filter(
                IMSRawData.upload_id == int(upload_id),
                IMSRawData.sheet_type == "official_actual_aggregate",
                IMSRawData.territory == "NATIONAL",
                IMSRawData.product_id.isnot(None),
            )
            .group_by(IMSRawData.product_id)
            .all()
        )
        if official_rows:
            return {
                int(product_id): float(value or 0.0)
                for product_id, value in official_rows
                if product_id is not None
            }

        metric_column = IMSFact.unit if metric_mode == self.METRIC_UNIT else IMSFact.tl
        fact_rows = (
            self.session.query(
                IMSFact.product_id,
                func.coalesce(func.sum(metric_column), 0.0),
            )
            .filter(
                IMSFact.upload_id == int(upload_id),
                IMSFact.report_type == "brick_sales",
            )
            .group_by(IMSFact.product_id)
            .all()
        )
        if fact_rows:
            return {
                int(product_id): float(value or 0.0)
                for product_id, value in fact_rows
                if product_id is not None
            }

        summary_column = IMSSummary.unit if metric_mode == self.METRIC_UNIT else IMSSummary.tl
        rows = (
            self.session.query(
                IMSSummary.product_id,
                func.coalesce(func.sum(summary_column), 0.0),
            )
            .filter(IMSSummary.upload_id == int(upload_id))
            .group_by(IMSSummary.product_id)
            .all()
        )
        return {int(product_id): float(value or 0.0) for product_id, value in rows if product_id is not None}

    def _company_tl_by_product(self, upload_id: Optional[int]) -> Dict[int, float]:
        return self._company_metric_by_product(upload_id, self.METRIC_TL)

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
        return max(
            candidates,
            key=lambda row: (
                float(getattr(row, "market_value", 0.0) or 0.0) > 0,
                float(getattr(row, "market_value", 0.0) or 0.0),
                float(getattr(row, "market_share", 0.0) or 0.0),
            ),
        )

    @staticmethod
    def _week(upload) -> Optional[int]:
        value = getattr(upload, "week_number", None) if upload is not None else None
        return int(value) if value is not None else None

    def _source_message(self, state, latest, source, metric_mode=None) -> str:
        latest_week = self._week(latest)
        source_week = self._week(source)
        metric_text = "KUTU bazlı " if metric_mode == self.METRIC_UNIT else ""
        if state == self.SOURCE_CURRENT:
            return (
                f"Veriler güncel {source_week}. hafta IMS dosyasından alınmıştır. "
                f"{metric_text}rekabet ve şirket IMS değerleri aynı haftaya aittir."
            ) if source_week else f"Veriler güncel IMS dosyasından alınmıştır. {metric_text}rekabet verisi aktiftir."
        if state == self.SOURCE_FALLBACK:
            return (
                f"{latest_week}. hafta IMS verisinde kullanılabilir rekabet analizi mevcut değil. "
                f"Tablodaki {metric_text}rekabet ve şirket IMS verileri son kullanılabilir kaynak olan "
                f"{source_week}. hafta IMS dosyasına aittir."
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
        metric_mode = (
            self._competition_metric(source.id)
            if source is not None and state != self.SOURCE_IMS_ONLY
            else None
        )
        competition_rows = self._competition_groups(
            source.id if source and state != self.SOURCE_IMS_ONLY else None,
            metric_mode,
        )

        company_tl_by_product = self._company_metric_by_product(
            data_upload.id if data_upload else None, self.METRIC_TL
        )
        company_unit_by_product = self._company_metric_by_product(
            data_upload.id if data_upload else None, self.METRIC_UNIT
        )

        products = (
            self.session.query(Product)
            .filter(Product.is_active.is_(True))
            .order_by(Product.display_order.asc(), Product.product_name.asc())
            .all()
        )

        groups = []
        market_total_value = 0.0
        company_market_total_value = 0.0
        company_total_tl = 0.0
        company_total_unit = 0.0

        for product in products:
            company_tl = float(company_tl_by_product.get(int(product.id), 0.0) or 0.0)
            company_unit = float(company_unit_by_product.get(int(product.id), 0.0) or 0.0)
            company_value = company_unit if metric_mode == self.METRIC_UNIT else company_tl

            selected = self._choose_market_row(self._match_candidates(product, competition_rows))
            market_available = selected is not None and float(getattr(selected, "market_value", 0.0) or 0.0) > 0
            market_value = float(getattr(selected, "market_value", 0.0) or 0.0) if market_available else None
            reported_share = float(getattr(selected, "market_share", 0.0) or 0.0) if selected is not None and getattr(selected, "market_share", None) is not None else None
            competitor_value = max(float(market_value) - company_value, 0.0) if market_available else None
            company_share = round(company_value * 100.0 / float(market_value), 2) if market_available and market_value else None

            company_total_tl += company_tl
            company_total_unit += company_unit
            if market_available:
                market_total_value += float(market_value)
                company_market_total_value += company_value

            groups.append(
                {
                    "product_id": int(product.id),
                    "company_product": product.product_name,
                    "product_group": getattr(selected, "product_group", None) if selected is not None else None,
                    "metric_mode": metric_mode,
                    "company_value": round(company_value, 2),
                    "market_value": round(float(market_value), 2) if market_value is not None else None,
                    "competitor_value": round(float(competitor_value), 2) if competitor_value is not None else None,
                    "company_sales_tl": round(company_tl, 2),
                    "company_sales_unit": round(company_unit, 2),
                    "market_sales_tl": round(float(market_value), 2) if metric_mode == self.METRIC_TL and market_value is not None else None,
                    "competitor_sales_tl": round(float(competitor_value), 2) if metric_mode == self.METRIC_TL and competitor_value is not None else None,
                    "market_sales_unit": round(float(market_value), 2) if metric_mode == self.METRIC_UNIT and market_value is not None else None,
                    "competitor_sales_unit": round(float(competitor_value), 2) if metric_mode == self.METRIC_UNIT and competitor_value is not None else None,
                    "company_share_percent": company_share,
                    "reported_market_share_percent": round(reported_share, 2) if reported_share is not None else None,
                    "market_available": bool(market_available),
                    "data_status": (
                        "REKABET KUTU + IMS" if market_available and metric_mode == self.METRIC_UNIT
                        else "REKABET TL + IMS" if market_available
                        else "YALNIZ IMS"
                    ),
                }
            )

        competitor_total_value = max(market_total_value - company_market_total_value, 0.0)
        source_week = self._week(source)
        latest_week = self._week(latest)
        company_total_value = company_total_unit if metric_mode == self.METRIC_UNIT else company_total_tl

        return {
            "year": self.year,
            "month": self.month,
            "latest_week": latest_week,
            "source_week": source_week,
            "source_state": state,
            "is_current": state == self.SOURCE_CURRENT,
            "is_fallback": state == self.SOURCE_FALLBACK,
            "has_competition": state != self.SOURCE_IMS_ONLY and bool(competition_rows),
            "metric_mode": metric_mode,
            "metric_label": "Kutu" if metric_mode == self.METRIC_UNIT else "TL",
            "metric_suffix": "kutu" if metric_mode == self.METRIC_UNIT else "₺",
            "source_message": self._source_message(state, latest, source, metric_mode),
            "source_file": getattr(data_upload, "file_name", None) if data_upload is not None else None,
            "company_total_value": round(company_total_value, 2),
            "market_total_value": round(market_total_value, 2),
            "competitor_total_value": round(competitor_total_value, 2),
            "market_total_tl": round(market_total_value, 2) if metric_mode == self.METRIC_TL else 0.0,
            "company_total_tl": round(company_total_tl, 2),
            "competitor_total_tl": round(competitor_total_value, 2) if metric_mode == self.METRIC_TL else 0.0,
            "market_total_unit": round(market_total_value, 2) if metric_mode == self.METRIC_UNIT else 0.0,
            "company_total_unit": round(company_total_unit, 2),
            "competitor_total_unit": round(competitor_total_value, 2) if metric_mode == self.METRIC_UNIT else 0.0,
            "company_share_percent": round(company_market_total_value * 100.0 / market_total_value, 2) if market_total_value else 0.0,
            "groups": groups,
        }
