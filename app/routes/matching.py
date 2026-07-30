"""Manual representative and product matching routes."""

from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import ManualMatchQueue, Product, Representative
from app.services.alias_service import AliasService

matching_bp = Blueprint("matching", __name__, url_prefix="/matching")


@matching_bp.route("/")
@login_required
def index():
    pending = ManualMatchQueue.query.filter_by(
        status=ManualMatchQueue.STATUS_PENDING
    ).order_by(ManualMatchQueue.created_at.desc()).all()

    resolved = ManualMatchQueue.query.filter(
        ManualMatchQueue.status != ManualMatchQueue.STATUS_PENDING
    ).order_by(ManualMatchQueue.resolved_at.desc()).limit(50).all()

    representatives = Representative.query.filter_by(active=True).order_by(
        Representative.rep_name.asc()
    ).all()
    products = Product.query.filter_by(is_active=True).order_by(
        Product.product_name.asc()
    ).all()

    return render_template(
        "matching.html",
        pending=pending,
        resolved=resolved,
        representatives=representatives,
        products=products,
    )


@matching_bp.route("/resolve/<int:queue_id>", methods=["POST"])
@login_required
def resolve(queue_id):
    entry = ManualMatchQueue.query.get_or_404(queue_id)
    target_id = request.form.get("target_id", type=int)
    create_alias = request.form.get("create_alias") == "1"

    if not target_id:
        flash("Lütfen bir eşleşme seçiniz.", "warning")
        return redirect(url_for("matching.index"))

    try:
        if entry.entity_type == ManualMatchQueue.ENTITY_REPRESENTATIVE:
            rep = Representative.query.get_or_404(target_id)
            AliasService.persist_representative_match(
                ims_name=entry.ims_name,
                representative=rep,
                method="MANUAL",
                score=100.0,
                created_by=current_user.full_name,
            )
            if create_alias:
                AliasService.create_representative_alias(rep, entry.ims_name)
        elif entry.entity_type == ManualMatchQueue.ENTITY_PRODUCT:
            product = Product.query.get_or_404(target_id)
            AliasService.persist_product_match(
                ims_name=entry.ims_name,
                product=product,
                method="MANUAL",
                score=100.0,
                created_by=current_user.full_name,
            )
            if create_alias:
                AliasService.create_product_alias(product, entry.ims_name)

        entry.status = ManualMatchQueue.STATUS_RESOLVED
        entry.resolved_by = current_user.full_name
        entry.resolved_at = datetime.utcnow()
        db.session.commit()
        flash(f"'{entry.ims_name}' başarıyla eşleştirildi.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Eşleştirme hatası: {exc}", "danger")

    return redirect(url_for("matching.index"))


@matching_bp.route("/ignore/<int:queue_id>", methods=["POST"])
@login_required
def ignore(queue_id):
    entry = ManualMatchQueue.query.get_or_404(queue_id)
    try:
        entry.status = ManualMatchQueue.STATUS_IGNORED
        entry.resolved_by = current_user.full_name
        entry.resolved_at = datetime.utcnow()
        db.session.commit()
        flash(f"'{entry.ims_name}' görmezden gelindi.", "info")
    except Exception as exc:
        db.session.rollback()
        flash(f"Hata: {exc}", "danger")
    return redirect(url_for("matching.index"))


@matching_bp.route("/api/pending")
@login_required
def api_pending():
    items = ManualMatchQueue.query.filter_by(
        status=ManualMatchQueue.STATUS_PENDING
    ).order_by(ManualMatchQueue.created_at.desc()).all()
    return jsonify({
        "success": True,
        "count": len(items),
        "items": [
            {
                "id": item.id,
                "entity_type": item.entity_type,
                "ims_name": item.ims_name,
                "best_candidate": item.best_candidate,
                "best_score": item.best_score,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
    })


@matching_bp.route("/api/suggestions")
@login_required
def api_suggestions():
    """Return fuzzy match suggestions for a given IMS name."""
    ims_name = request.args.get("q", "").strip()
    entity_type = request.args.get("type", ManualMatchQueue.ENTITY_REPRESENTATIVE)

    if not ims_name:
        return jsonify({"success": False, "error": "Query required"}), 400

    suggestions = []
    if entity_type == ManualMatchQueue.ENTITY_REPRESENTATIVE:
        for rep in Representative.query.filter_by(active=True).all():
            score = AliasService.similarity(ims_name, rep.rep_name) * 100
            if score >= 40:
                suggestions.append({"id": rep.id, "name": rep.rep_name, "score": round(score, 1)})
    else:
        for product in Product.query.filter_by(is_active=True).all():
            score = AliasService.similarity(ims_name, product.product_name) * 100
            if score >= 40:
                suggestions.append({"id": product.id, "name": product.product_name, "score": round(score, 1)})

    suggestions.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({"success": True, "suggestions": suggestions[:10]})
