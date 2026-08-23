from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required

from app.models import Product, Representative
from app.services.simulation_service import SimulationService


simulation_bp = Blueprint("simulation", __name__, url_prefix="/simulation")


def _as_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_overrides(data):
    overrides = {}
    duplicates = []
    seen = set()
    for item in data.get("products", []):
        product_id = int(item.get("product_id", 0) or 0)
        if product_id <= 0:
            continue
        if product_id in seen:
            duplicates.append(product_id)
            continue
        seen.add(product_id)

        mode = str(item.get("mode", "delta")).strip().lower() or "delta"
        unit = _as_float(item.get("unit"))
        tl = _as_float(item.get("tl"))
        unit_delta = _as_float(item.get("unit_delta"))
        tl_delta = _as_float(item.get("tl_delta"))
        slider_percent = _as_float(item.get("slider_percent"))
        target_percent = _as_float(item.get("target_percent"))

        if mode == "replace":
            has_change = any(value is not None for value in [unit, tl, slider_percent, target_percent])
        else:
            unit_delta = unit_delta if unit_delta is not None else (unit or 0.0)
            tl_delta = tl_delta if tl_delta is not None else (tl or 0.0)
            # A box-only scenario represents real additional sales.  Keep the
            # TL delta unset so PrimeEngine can value it using that period's
            # product target/unit ratio rather than treating it as zero ciro.
            if abs(unit_delta or 0.0) > 0 and abs(tl_delta or 0.0) == 0:
                tl_delta = None
            has_change = any(
                abs(value) > 0 for value in [unit_delta, tl_delta] if value is not None
            ) or slider_percent not in (None, 100.0) or target_percent is not None

        if not has_change:
            continue

        override = {"mode": mode}
        if mode == "replace":
            if unit is not None:
                override["unit"] = unit
            if tl is not None:
                override["tl"] = tl
        else:
            if unit_delta is not None:
                override["unit_delta"] = unit_delta
            if tl_delta is not None:
                override["tl_delta"] = tl_delta
        if slider_percent is not None:
            override["slider_percent"] = slider_percent
        if target_percent is not None:
            override["target_percent"] = target_percent
        overrides[product_id] = override
    return overrides, duplicates


def _validated_service(data):
    representative_id = int(data.get("representative_id", 0) or 0)
    year = int(data.get("year", 0) or 0)
    month = int(data.get("month", 0) or 0)

    if representative_id <= 0:
        raise ValueError("Temsilci seçiniz.")
    if year <= 0:
        raise ValueError("Yıl bilgisi eksik.")
    if month < 1 or month > 12:
        raise ValueError("Geçersiz ay.")

    overrides, duplicates = build_overrides(data)
    if duplicates:
        raise ValueError("Aynı ürün birden fazla gönderildi.")

    return SimulationService(
        representative_id=representative_id,
        year=year,
        month=month,
        overrides=overrides,
    )


def _server_error(message, exc):
    current_app.logger.exception(message, exc_info=exc)
    return jsonify({"success": False, "message": "İşlem sırasında beklenmeyen bir hata oluştu."}), 500


@simulation_bp.route("/", methods=["GET"])
@login_required
def index():
    representatives = Representative.query.filter_by(active=True).all()
    representatives.sort(
        key=lambda representative: (
            str(representative.rep_name or "").strip().upper().startswith(("ATANMAMIŞ", "ATANMAMIS")),
            str(representative.rep_name or "").strip().upper(),
        )
    )
    products = Product.query.filter_by(is_active=True).order_by(Product.display_order.asc()).all()
    return render_template("simulation.html", representatives=representatives, products=products)


@simulation_bp.route("/calculate", methods=["POST"])
@login_required
def calculate():
    try:
        data = request.get_json() or {}
        service = _validated_service(data)
        return jsonify(service.report())
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return _server_error("Simulation calculate failed", exc)


@simulation_bp.route("/history", methods=["POST"])
@login_required
def history():
    try:
        data = request.get_json() or {}
        service = _validated_service(data)
        return jsonify({"success": True, "history": service.history()})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return _server_error("Simulation history failed", exc)


@simulation_bp.route("/export/pdf", methods=["POST"])
@login_required
def export_pdf():
    try:
        data = request.get_json() or {}
        report_type = data.get("report_type", "prime_report")
        service = _validated_service(data)
        export = service.export_pdf(report_type=report_type)
        return jsonify({"success": True, "export": export})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return _server_error("Simulation PDF export failed", exc)


@simulation_bp.route("/export/excel", methods=["POST"])
@login_required
def export_excel():
    try:
        data = request.get_json() or {}
        service = _validated_service(data)
        export = service.export_excel()
        return jsonify({"success": True, "export": export})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return _server_error("Simulation Excel export failed", exc)


@simulation_bp.route("/product/<int:product_id>")
@login_required
def product_info(product_id):
    product = Product.query.get_or_404(product_id)
    return jsonify(
        {
            "id": product.id,
            "code": product.product_code,
            "name": product.product_name,
            "unit_price": product.unit_price,
            "required_percent": product.required_percent,
            "include_total_tl": product.include_total_tl,
            "active": product.is_active,
            "display_order": product.display_order,
            "prime_product": product.is_prime_product,
            "category": product.category,
            "molecule": product.molecule,
            "strength": product.strength,
            "dosage_form": product.dosage_form,
        }
    )


@simulation_bp.route("/representative/<int:rep_id>")
@login_required
def representative_info(rep_id):
    representative = Representative.query.get_or_404(rep_id)
    return jsonify(
        {
            "id": representative.id,
            "code": representative.rep_code,
            "ims_code": representative.ims_code,
            "name": representative.rep_name,
            "manager": representative.manager,
            "region": representative.region,
            "city": representative.city,
            "territory": representative.territory,
            "team": representative.team,
            "email": representative.email,
            "phone": representative.phone,
            "active": representative.active,
        }
    )


@simulation_bp.route("/health")
@login_required
def health():
    return jsonify(
        {
            "success": True,
            "module": "Simulation",
            "service": SimulationService.health(),
            "capabilities": SimulationService.capabilities(),
        }
    )


@simulation_bp.route("/validate", methods=["POST"])
@login_required
def validate():
    data = request.get_json() or {}
    errors = []
    representative_id = int(data.get("representative_id", 0) or 0)
    year = int(data.get("year", 0) or 0)
    month = int(data.get("month", 0) or 0)

    if representative_id <= 0:
        errors.append("Temsilci seçilmedi.")
    elif Representative.query.get(representative_id) is None:
        errors.append("Temsilci bulunamadı.")

    if year <= 0:
        errors.append("Geçersiz yıl.")
    if month < 1 or month > 12:
        errors.append("Geçersiz ay.")

    overrides, duplicates = build_overrides(data)
    if duplicates:
        errors.append("Aynı ürün birden fazla gönderildi.")
    for product_id in overrides.keys():
        if Product.query.get(product_id) is None:
            errors.append(f"Ürün bulunamadı ({product_id})")

    return jsonify(
        {
            "success": len(errors) == 0,
            "errors": errors,
            "override_count": len(overrides),
        }
    )
