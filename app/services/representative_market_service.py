"""Representative-scoped company and competitor market analysis."""

from collections import defaultdict
import logging
from pathlib import Path
from types import SimpleNamespace

from flask import current_app
from sqlalchemy import desc

from app.extensions import db
from app.models import CompetitionData, IMSRawData, IMSSummary, IMSUpload, Product, RepresentativeBrickAssignment, Target
from app.services.alias_service import AliasService
from app.services.competition_import_service import CompetitionImportService
from app.services.production_result_service import ProductionResultService


logger = logging.getLogger(__name__)


class RepresentativeMarketService:
    """Build a seven-product market view without leaking another rep's bricks."""

    _workbook_competition_cache = {}

    PRODUCT_ORDER = (
        "TRAVAZOL",
        "MONUROL",
        "ACNEMIX",
        "MIXOVUL",
        "STIDERM",
        "BRIMODER",
        "FENTIVAG",
    )

    def __init__(self, representative, year, month):
        self.representative = representative
        self.year = int(year)
        self.month = int(month)

    @staticmethod
    def _key(value):
        return "".join(ch for ch in AliasService.normalize(value) if ch.isalnum())

    def _products(self):
        products = Product.query.order_by(
            Product.display_order.asc(), Product.product_name.asc()
        ).all()
        by_key = {self._key(product.product_name): product for product in products}
        ordered = []
        for name in self.PRODUCT_ORDER:
            product = next(
                (
                    item
                    for key, item in by_key.items()
                    if name in key or key in name
                ),
                None,
            )
            if product is not None and product not in ordered:
                ordered.append(product)
        for product in products:
            if product not in ordered and len(ordered) < 7:
                ordered.append(product)
        return ordered[:7]

    def _scope(self):
        assignments = RepresentativeBrickAssignment.query.filter_by(
            representative_id=self.representative.id,
            year=self.year,
            month=self.month,
            active=True,
        ).all()
        brick_keys = {self._key(item.brick) for item in assignments if self._key(item.brick)}
        fallback_keys = {
            self._key(value)
            for value in (
                self.representative.territory,
                self.representative.city,
                self.representative.region,
            )
            if self._key(value)
        }
        return assignments, brick_keys, fallback_keys

    @staticmethod
    def _latest_upload_id(year, month):
        return db.session.query(IMSUpload.id).filter(
            IMSUpload.year == year,
            IMSUpload.month == month,
            IMSUpload.status == "COMPLETED",
        ).order_by(desc(IMSUpload.completed_at), desc(IMSUpload.id)).limit(1).scalar()

    def _competition_rows(self, brick_keys, fallback_keys, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = self._latest_upload_id(year, month)
        if upload_id is None:
            return None, []

        rows = CompetitionData.query.filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
            CompetitionData.metric_type.in_(("TL", "UNIT", "MARKET_SHARE")),
        ).all()
        representative_key = self._key(self.representative.rep_name)
        representative_rows = [row for row in rows if self._key(row.subterritory) == representative_key]
        if representative_rows:
            return upload_id, representative_rows

        scope_keys = brick_keys or fallback_keys
        if not scope_keys:
            return upload_id, []
        scoped = [
            row
            for row in rows
            if self._key(row.subterritory) in scope_keys or self._key(row.territory) in scope_keys
        ]
        return upload_id, scoped

    def _brick_raw_rows(self, year=None, month=None):
        """Return latest source rows for every brick assigned to the rep.

        A shared brick is stored once under the primary Excel representative,
        but both people are members of that brick.  Scoping by membership (and
        not by the raw row owner) lets both individual analysis pages show the
        same source values without duplicating national facts.
        """
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = self._latest_upload_id(year, month)
        assignments = RepresentativeBrickAssignment.query.filter_by(
            representative_id=self.representative.id, year=year, month=month, active=True
        ).all()
        brick_keys = {self._key(item.brick) for item in assignments if self._key(item.brick)}
        if upload_id is None or not brick_keys:
            return None, []
        candidates = IMSRawData.query.filter(
            IMSRawData.upload_id == upload_id,
            IMSRawData.year == year,
            IMSRawData.month == month,
            IMSRawData.brick.isnot(None),
            IMSRawData.product_id.isnot(None),
            IMSRawData.sheet_type.in_(("brick_sales", "competition_box")),
        ).all()
        rows = [row for row in candidates if self._key(row.brick) in brick_keys]
        return upload_id, rows

    def _shared_target_fallback(self, targets, assignments):
        """Use a co-worker's target only for an identical shared brick scope.

        Targets have representative grain in the workbook.  Therefore a
        partial overlap cannot be allocated safely.  If this representative
        has no target rows and another member has exactly the same complete
        brick set, the Excel scope is demonstrably common and the same target
        may be displayed on both pages without inserting a second DB record.
        """
        if targets or not assignments:
            return targets
        own_keys = {self._key(item.brick) for item in assignments if self._key(item.brick)}
        if not own_keys:
            return targets
        co_members = db.session.query(RepresentativeBrickAssignment.representative_id).filter(
            RepresentativeBrickAssignment.year == self.year,
            RepresentativeBrickAssignment.month == self.month,
            RepresentativeBrickAssignment.active.is_(True),
            RepresentativeBrickAssignment.representative_id != self.representative.id,
        ).distinct().all()
        for (representative_id,) in co_members:
            member_assignments = RepresentativeBrickAssignment.query.filter_by(
                representative_id=representative_id, year=self.year, month=self.month, active=True
            ).all()
            member_keys = {self._key(item.brick) for item in member_assignments if self._key(item.brick)}
            if member_keys != own_keys:
                continue
            member_targets = Target.query.filter_by(
                representative_id=representative_id, year=self.year, month=self.month
            ).all()
            if member_targets:
                return {item.product_id: item for item in member_targets}
        return targets

    def _brick_competition_rows(self, brick_keys):
        """Return exact product-level UNIT rows from monthly brick competition."""
        upload_id = self._latest_upload_id(self.year, self.month)
        if upload_id is None or not brick_keys:
            return None, []
        rows = CompetitionData.query.filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.metric_type == "UNIT",
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
        ).all()
        exact = [
            row for row in rows
            if self._key(row.subterritory) in brick_keys
            and "AYLIK" in AliasService.normalize(row.sheet_name)
            and "REKABET" in AliasService.normalize(row.sheet_name)
            and "KUTU" in AliasService.normalize(row.sheet_name)
        ]
        if not exact:
            exact = self._brick_competition_rows_from_workbook(upload_id, brick_keys)
        return upload_id, exact

    def _brick_competition_rows_from_workbook(self, upload_id, brick_keys):
        """Read exact named brick products from the retained source workbook.

        This is a read-only compatibility path for uploads completed before
        product-level monthly competition rows were persisted. New uploads use
        the database path above. The parsed source is cached per upload so the
        workbook is read only once per application process.
        """
        cached = self._workbook_competition_cache.get(upload_id)
        if cached is None:
            upload = db.session.get(IMSUpload, upload_id)
            upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
            workbook_path = upload_folder / upload.file_name if upload else None
            cached = []
            if workbook_path and workbook_path.is_file():
                parser = CompetitionImportService(
                    file_path=str(workbook_path), upload_id=upload_id,
                    year=self.year, month=self.month,
                )
                try:
                    parser.load_workbook(str(workbook_path))
                    for sheet_name in parser.get_supported_sheets():
                        normalized = AliasService.normalize(sheet_name)
                        if not ("AYLIK" in normalized and "REKABET" in normalized and "KUTU" in normalized):
                            continue
                        structure = parser._parse_sheet_structure(sheet_name)
                        for record in parser._parse_sheet_records(structure):
                            cached.append(SimpleNamespace(
                                subterritory=record.get("subterritory"),
                                territory=record.get("territory"),
                                product_group=record.get("product_group"),
                                product_name=record.get("product_name"),
                                metric_type=record.get("metric_type"),
                                metric_value=record.get("metric_value"),
                                sheet_name=record.get("sheet_name"),
                                is_subtotal=False,
                                is_grand_total=False,
                            ))
                except Exception:
                    logger.exception("brick_competition_source_read_failed upload_id=%s", upload_id)
                finally:
                    if parser._workbook:
                        parser._workbook.close()
            self._workbook_competition_cache[upload_id] = cached
        return [row for row in cached if self._key(row.subterritory) in brick_keys]

    def _product_for_row(self, row, products):
        group_key = self._key(row.product_group)
        product_key = self._key(row.product_name)
        for product in products:
            candidates = {
                self._key(product.product_name),
                self._key(product.product_code),
                self._key(product.ims_name),
                self._key(product.competitor_group),
            } - {""}
            if any(key in group_key or key in product_key for key in candidates):
                return product
        return None

    def _is_company_product(self, row, product):
        return self._is_company_product_name(row.product_name, product)

    def _is_company_product_name(self, product_name, product):
        product_key = self._key(product_name)
        own_keys = {
            self._key(product.product_name),
            self._key(product.product_code),
            self._key(product.ims_name),
        } - {""}
        return any(key in product_key or product_key in key for key in own_keys)

    @staticmethod
    def _is_subtotal_product_name(product_name):
        normalized = AliasService.normalize(product_name)
        return "SUBTOTAL" in normalized or "ARA TOPLAM" in normalized or normalized.endswith(" TOPLAM") or normalized.endswith(" TOTAL")

    def build(self):
        products = self._products()
        assignments, brick_keys, fallback_keys = self._scope()
        upload_id, competition_rows = self._competition_rows(brick_keys, fallback_keys)
        brick_upload_id, brick_raw_rows = self._brick_raw_rows()
        _, brick_competition_rows = self._brick_competition_rows(brick_keys)
        previous_year = self.year if self.month > 1 else self.year - 1
        previous_month = self.month - 1 if self.month > 1 else 12
        previous_upload_id, previous_competition_rows = self._competition_rows(
            brick_keys, fallback_keys, previous_year, previous_month
        )
        summaries = {
            item.product_id: item
            for item in IMSSummary.query.filter_by(
                representative_id=self.representative.id,
                year=self.year,
                month=self.month,
            ).all()
        }
        previous_summaries = {
            item.product_id: item
            for item in IMSSummary.query.filter_by(
                representative_id=self.representative.id,
                year=previous_year,
                month=previous_month,
            ).all()
        }
        targets = {
            item.product_id: item
            for item in Target.query.filter_by(
                representative_id=self.representative.id,
                year=self.year,
                month=self.month,
            ).all()
        }
        targets = self._shared_target_fallback(targets, assignments)

        # Representative summaries remain single-owner facts.  For a brick
        # scoped profile, source sales are the authoritative view and include
        # common rows for every assigned co-worker.
        scoped_actuals = defaultdict(float)
        for raw in brick_raw_rows:
            if raw.sheet_type == "brick_sales":
                scoped_actuals[raw.product_id] += float(raw.unit or 0.0)

        grouped = defaultdict(lambda: {"unit": 0.0, "subtotal_unit": 0.0, "rivals": defaultdict(float)})
        brick_groups = defaultdict(
            lambda: {
                "company_unit": 0.0,
                "market_unit": 0.0,
                "products": defaultdict(
                    lambda: {
                        "company_unit": 0.0,
                        "exact_company_unit": 0.0,
                        "market_unit": 0.0,
                        "subtotal_unit": 0.0,
                        "market_products": defaultdict(float),
                    }
                ),
            }
        )
        use_raw_bricks = bool(brick_raw_rows)
        use_exact_brick_competition = bool(brick_competition_rows)
        for row in competition_rows:
            if row.metric_type != "UNIT":
                continue
            product = self._product_for_row(row, products)
            if product is None:
                continue
            bucket = grouped[product.id]
            value = float(row.metric_value or 0.0)
            if self._is_subtotal_product_name(row.product_name):
                bucket["subtotal_unit"] += value
                if not use_raw_bricks:
                    brick = str(row.subterritory or row.territory or "Brick bilgisi yok").strip()
                    brick_groups[brick]["products"][product.product_name]["subtotal_unit"] += value
                continue
            bucket["unit"] += value
            is_company = self._is_company_product(row, product)
            if not is_company:
                bucket["rivals"][row.product_name] += value

            if use_raw_bricks:
                continue
            brick = str(row.subterritory or row.territory or "Brick bilgisi yok").strip()
            brick_bucket = brick_groups[brick]
            brick_bucket["market_unit"] += value
            product_bucket = brick_bucket["products"][product.product_name]
            product_bucket["market_unit"] += value
            product_bucket["market_products"][str(row.product_name or "Ürün adı yok").strip()] += value
            if is_company:
                brick_bucket["company_unit"] += value
                product_bucket["company_unit"] += value

        if use_raw_bricks:
            products_by_id = {product.id: product for product in products}
            for raw in brick_raw_rows:
                product = products_by_id.get(raw.product_id)
                brick = str(raw.brick or "").strip()
                if product is None or not brick:
                    continue
                product_bucket = brick_groups[brick]["products"][product.product_name]
                value = float(raw.unit or 0.0)
                if raw.sheet_type == "brick_sales":
                    product_bucket["company_unit"] += value
                elif raw.sheet_type == "competition_box" and not use_exact_brick_competition:
                    product_bucket["market_unit"] += value

        if use_exact_brick_competition:
            for row in brick_competition_rows:
                product = self._product_for_row(row, products)
                brick = str(row.subterritory or "").strip()
                if product is None or not brick:
                    continue
                value = float(row.metric_value or 0.0)
                product_bucket = brick_groups[brick]["products"][product.product_name]
                if self._is_subtotal_product_name(row.product_name):
                    product_bucket["subtotal_unit"] += value
                    continue
                product_bucket["market_unit"] += value
                product_bucket["market_products"][str(row.product_name).strip()] += value
                if self._is_company_product(row, product):
                    product_bucket["exact_company_unit"] += value

            for brick_data in brick_groups.values():
                for product_data in brick_data["products"].values():
                    product_data["company_unit"] = product_data["exact_company_unit"]

        for brick_data in brick_groups.values():
            brick_data["company_unit"] = 0.0
            brick_data["market_unit"] = 0.0
            for product_data in brick_data["products"].values():
                brick_data["company_unit"] += product_data["company_unit"]
                brick_data["market_unit"] += product_data["market_unit"]

        # Analysis totals only use product detail rows. Excel subtotal values
        # remain separate display KPIs, preventing duplicate aggregation.
        products_by_name = {product.product_name: product for product in products}
        if not use_raw_bricks:
            for market in grouped.values():
                market["unit"] = 0.0
                market["subtotal_unit"] = 0.0
            for brick_data in brick_groups.values():
                for product_name, product_data in brick_data["products"].items():
                    product = products_by_name.get(product_name)
                    if product is not None:
                        grouped[product.id]["unit"] += product_data["market_unit"]

        previous_grouped = defaultdict(lambda: {"unit": 0.0, "subtotal_unit": 0.0})
        for row in previous_competition_rows:
            if row.metric_type != "UNIT":
                continue
            product = self._product_for_row(row, products)
            if product is not None:
                key = "subtotal_unit" if self._is_subtotal_product_name(row.product_name) else "unit"
                previous_grouped[product.id][key] += float(row.metric_value or 0.0)

        rows = []
        for product in products:
            summary = summaries.get(product.id)
            # The persisted summary is authoritative for the primary owner.
            # A co-worker without a duplicated summary receives the same
            # shared-brick source value in the analysis view.
            actual_unit = (
                float(summary.unit)
                if summary is not None
                else float(scoped_actuals.get(product.id, 0.0))
            )
            market = grouped[product.id]
            market_unit = float(market["unit"])
            competitor_unit = max(market_unit - actual_unit, 0.0)
            previous_summary = previous_summaries.get(product.id)
            previous_actual_unit = float(previous_summary.unit or 0.0) if previous_summary else 0.0
            previous_market = previous_grouped[product.id]
            previous_market_unit = float(previous_market["unit"])
            previous_competitor_unit = max(previous_market_unit - previous_actual_unit, 0.0)
            has_previous = previous_summary is not None or previous_market_unit > 0
            actual_change_unit = actual_unit - previous_actual_unit
            competitor_change_unit = competitor_unit - previous_competitor_unit
            actual_change_percent = actual_change_unit * 100.0 / previous_actual_unit if previous_actual_unit else None
            target_unit = float(targets.get(product.id).unit_target or 0.0) if targets.get(product.id) else 0.0
            effective = ProductionResultService.effective_product(self.year, self.month, self.representative.id, product.id)
            if effective.get("source", "IMS").startswith("PRODUCTION_"):
                actual_unit = float(effective.get("actual_unit") or 0)
            calculated_share = actual_unit * 100.0 / market_unit if market_unit else 0.0
            rivals = sorted(market["rivals"].items(), key=lambda item: item[1], reverse=True)[:5]
            rows.append(
                {
                    "product": product,
                    "actual_unit": round(actual_unit, 2),
                    "market_unit": round(market_unit, 2),
                    "competitor_unit": round(competitor_unit, 2),
                    "share_percent": round(calculated_share, 1),
                    "gap_unit": round(competitor_unit - actual_unit, 2),
                    "has_previous": has_previous,
                    "previous_actual_unit": round(previous_actual_unit, 2),
                    "actual_change_unit": round(actual_change_unit, 2),
                    "actual_change_percent": round(actual_change_percent, 1) if actual_change_percent is not None else None,
                    "previous_competitor_unit": round(previous_competitor_unit, 2),
                    "competitor_change_unit": round(competitor_change_unit, 2),
                    "target_unit": target_unit,
                    "realization_percent": float(effective.get("realization_percent") or 0),
                    "realization_source": effective.get("source", "IMS"),
                    "attention": "critical" if competitor_unit > actual_unit * 1.5 and competitor_unit > 0 else "warning" if competitor_unit > actual_unit else "strong",
                    "rivals": [{"name": name, "unit": round(value, 2)} for name, value in rivals],
                }
            )

        total_actual = sum(item["actual_unit"] for item in rows)
        total_market = sum(item["market_unit"] for item in rows)
        average_competitor = (
            sum(max(item["market_unit"] - item["company_unit"], 0.0) for item in brick_groups.values())
            / len(brick_groups)
            if brick_groups else 0.0
        )
        brick_rows = []
        for brick, item in brick_groups.items():
            company_unit = item["company_unit"]
            market_unit = item["market_unit"]
            competitor_unit = max(market_unit - company_unit, 0.0)
            delta_unit = competitor_unit - company_unit
            if competitor_unit >= average_competitor * 1.5 and competitor_unit > company_unit and competitor_unit > 0:
                attention, label, arrow = "critical", "Öncelikli bölge", "↑"
            elif competitor_unit > average_competitor or competitor_unit > company_unit:
                attention, label, arrow = "warning", "Takip edilmeli", "↗"
            else:
                attention, label, arrow = "strong", "Güçlü / dengeli", "→"
            threats = []
            for product_name, product_data in item["products"].items():
                rival_units = max(product_data["market_unit"] - product_data["company_unit"], 0.0)
                if rival_units > product_data["company_unit"]:
                    threats.append(
                        {
                            "product_name": product_name,
                            "competitor_unit": round(rival_units, 2),
                            "gap_unit": round(rival_units - product_data["company_unit"], 2),
                        }
                    )
            threats.sort(key=lambda threat: threat["gap_unit"], reverse=True)
            brick_rows.append(
                {
                    "brick": brick,
                    "company_unit": round(company_unit, 2),
                    "competitor_unit": round(competitor_unit, 2),
                    "market_unit": round(market_unit, 2),
                    "share_percent": round(company_unit * 100.0 / market_unit, 1) if market_unit else 0.0,
                    "delta_unit": round(delta_unit, 2),
                    "attention": attention,
                    "attention_label": label,
                    "arrow": arrow,
                    "threats": threats[:3],
                }
            )
        priority = {"critical": 0, "warning": 1, "strong": 2}
        brick_rows.sort(key=lambda item: (priority[item["attention"]], -item["competitor_unit"]))
        brick_product_rows = []
        for brick, brick_data in brick_groups.items():
            for product_name, product_data in brick_data["products"].items():
                product = products_by_name.get(product_name)
                target = targets.get(product.id) if product else None
                target_unit = float(target.unit_target or 0.0) if target else 0.0
                company_unit = float(product_data["company_unit"])
                market_unit = float(product_data["market_unit"])
                competitor_unit = max(market_unit - company_unit, 0.0)
                market_products = []
                if use_raw_bricks and not use_exact_brick_competition:
                    rival_unit = max(market_unit - company_unit, 0.0)
                    for market_product_name, market_product_unit, is_company in (
                        (product_name, company_unit, True),
                        ("Rakip toplamı", rival_unit, False),
                    ):
                        market_products.append({
                            "name": market_product_name,
                            "unit": round(float(market_product_unit), 2),
                            "is_company": is_company,
                            "share_percent": round(float(market_product_unit) * 100.0 / market_unit, 1) if market_unit else 0.0,
                            "realization_percent": round(float(market_product_unit) * 100.0 / target_unit, 1) if is_company and target_unit else None,
                        })
                else:
                    for market_product_name, market_product_unit in product_data["market_products"].items():
                        is_company = self._is_company_product_name(market_product_name, product) if product else False
                        market_products.append({
                            "name": market_product_name,
                            "unit": round(float(market_product_unit), 2),
                            "is_company": is_company,
                            "share_percent": round(float(market_product_unit) * 100.0 / market_unit, 1) if market_unit else 0.0,
                            "realization_percent": round(float(market_product_unit) * 100.0 / target_unit, 1) if is_company and target_unit else None,
                        })
                market_products.sort(key=lambda item: (not item["is_company"], -item["unit"], item["name"]))
                brick_product_rows.append({
                    "brick": brick,
                    "product_name": product_name,
                    "company_unit": round(company_unit, 2),
                    "competitor_unit": round(competitor_unit, 2),
                    "market_unit": round(market_unit, 2),
                    "subtotal_unit": round(float(product_data["subtotal_unit"]), 2),
                    "group_total_unit": round(
                        float(product_data["subtotal_unit"] or market_unit), 2
                    ),
                    "target_unit": round(target_unit, 2),
                    "realization_percent": round(company_unit * 100.0 / target_unit, 1) if target_unit else 0.0,
                    "share_percent": round(company_unit * 100.0 / market_unit, 1) if market_unit else 0.0,
                    "market_products": market_products,
                })
        brick_product_rows.sort(key=lambda item: (item["brick"], item["product_name"]))
        return {
            "rows": rows,
            "chart_rows": [
                {
                    "product_name": item["product"].product_name,
                    "actual_unit": item["actual_unit"],
                    "competitor_unit": item["competitor_unit"],
                }
                for item in rows
            ],
            "brick_rows": brick_rows,
            "brick_product_rows": brick_product_rows,
            "upload_id": upload_id,
            "brick_upload_id": brick_upload_id,
            "previous_upload_id": previous_upload_id,
            "previous_period": {"year": previous_year, "month": previous_month},
            "scope": "brick" if brick_keys else "geography" if fallback_keys else "none",
            "bricks": [item.brick for item in assignments],
            "has_competition": bool(competition_rows),
            "totals": {
                "actual_unit": round(total_actual, 2),
                "market_unit": round(total_market, 2),
                "competitor_unit": round(max(total_market - total_actual, 0.0), 2),
                "share_percent": round(total_actual * 100.0 / total_market, 1) if total_market else 0.0,
            },
        }
