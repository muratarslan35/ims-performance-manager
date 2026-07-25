from datetime import datetime

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for
)

from flask_login import login_required
from flask_login import current_user

from sqlalchemy import and_

from app.extensions import db

from app.models import (
    AuditLog,
    PrimeRule,
    Product
)

prime_rules_bp = Blueprint(

    "prime_rules",

    __name__,

    url_prefix="/prime-rules"

)


def log_action(action):

    db.session.add(

        AuditLog(

            username=current_user.full_name,

            module="Prime Rules",

            action=action

        )

    )


@prime_rules_bp.route("/")
@login_required
def index():

    rules = PrimeRule.query.order_by(

        PrimeRule.active.desc(),

        PrimeRule.product_id.asc(),

        PrimeRule.valid_from.desc()

    ).all()

    products = Product.query.filter_by(

        is_active=True

    ).order_by(

        Product.display_order.asc(),

        Product.product_name.asc()

    ).all()

    return render_template(

        "prime_rules.html",

        rules=rules,

        products=products

    )


@prime_rules_bp.route("/api")
@login_required
def api():

    rules = PrimeRule.query.order_by(

        PrimeRule.product_id.asc()

    ).all()

    data = []

    for rule in rules:

        data.append({

            "id": rule.id,

            "product": rule.product.product_name,

            "required_percent": rule.required_percent,

            "include_prime": rule.include_in_prime,

            "include_total": rule.include_in_total_tl,

            "active": rule.active,

            "valid_from": str(rule.valid_from),

            "valid_to": str(rule.valid_to)

        })

    return jsonify(data)

def validate_rule(

    product_id,

    valid_from,

    valid_to,

    ignore_id=None

):

    query = PrimeRule.query.filter_by(

        product_id=product_id,

        active=True

    )

    if ignore_id:

        query = query.filter(

            PrimeRule.id != ignore_id

        )

    for rule in query.all():

        start = rule.valid_from

        end = rule.valid_to

        if start is None:

            start = datetime(

                1900,

                1,

                1

            ).date()

        if end is None:

            end = datetime(

                2999,

                12,

                31

            ).date()

        new_start = valid_from or datetime(

            1900,

            1,

            1

        ).date()

        new_end = valid_to or datetime(

            2999,

            12,

            31

        ).date()

        if not (

            new_end < start

            or

            new_start > end

        ):

            return False

    return True


@prime_rules_bp.route(

    "/add",

    methods=["POST"]

)
@login_required
def add():

    try:

        product_id = int(

            request.form["product"]

        )

        required_percent = int(

            request.form["required_percent"]

        )

        include_prime = (

            request.form.get(

                "include_prime"

            )

            is not None

        )

        include_total = (

            request.form.get(

                "include_total"

            )

            is not None

        )

        valid_from = request.form.get(

            "valid_from"

        )

        valid_to = request.form.get(

            "valid_to"

        )

        valid_from = (

            datetime.strptime(

                valid_from,

                "%Y-%m-%d"

            ).date()

            if valid_from else None

        )

        valid_to = (

            datetime.strptime(

                valid_to,

                "%Y-%m-%d"

            ).date()

            if valid_to else None

        )

        if not validate_rule(

            product_id,

            valid_from,

            valid_to

        ):

            flash(

                "Bu tarih aralığında aktif bir kural zaten mevcut.",

                "warning"

            )

            return redirect(

                url_for(

                    "prime_rules.index"

                )

            )

        rule = PrimeRule(

            product_id=product_id,

            required_percent=required_percent,

            include_in_prime=include_prime,

            include_in_total_tl=include_total,

            valid_from=valid_from,

            valid_to=valid_to,

            active=True

        )

        db.session.add(

            rule

        )

        log_action(

            "Yeni prim kuralı oluşturuldu."

        )

        db.session.commit()

        flash(

            "Prim kuralı başarıyla oluşturuldu.",

            "success"

        )

    except Exception as e:

        db.session.rollback()

        flash(

            str(e),

            "danger"

        )

    return redirect(

        url_for(

            "prime_rules.index"

        )

    )


@prime_rules_bp.route(

    "/edit/<int:rule_id>",

    methods=["POST"]

)
@login_required
def edit(

    rule_id

):

    rule = PrimeRule.query.get_or_404(

        rule_id

    )

    try:

        product_id = int(

            request.form["product"]

        )

        required_percent = int(

            request.form["required_percent"]

        )

        include_prime = (

            request.form.get(

                "include_prime"

            )

            is not None

        )

        include_total = (

            request.form.get(

                "include_total"

            )

            is not None

        )

        valid_from = request.form.get(

            "valid_from"

        )

        valid_to = request.form.get(

            "valid_to"

        )

        valid_from = (

            datetime.strptime(

                valid_from,

                "%Y-%m-%d"

            ).date()

            if valid_from else None

        )

        valid_to = (

            datetime.strptime(

                valid_to,

                "%Y-%m-%d"

            ).date()

            if valid_to else None

        )

        if not validate_rule(

            product_id,

            valid_from,

            valid_to,

            ignore_id=rule.id

        ):

            flash(

                "Kural tarihleri çakışıyor.",

                "warning"

            )

            return redirect(

                url_for(

                    "prime_rules.index"

                )

            )

        rule.product_id = product_id

        rule.required_percent = required_percent

        rule.include_in_prime = include_prime

        rule.include_in_total_tl = include_total

        rule.valid_from = valid_from

        rule.valid_to = valid_to

        log_action(

            f"Prim kuralı güncellendi (#{rule.id})"

        )

        db.session.commit()

        flash(

            "Prim kuralı güncellendi.",

            "success"

        )

    except Exception as e:

        db.session.rollback()

        flash(

            str(e),

            "danger"

        )

    return redirect(

        url_for(

            "prime_rules.index"

        )

    )

@prime_rules_bp.route(

    "/toggle/<int:rule_id>"

)
@login_required
def toggle(

    rule_id

):

    rule = PrimeRule.query.get_or_404(

        rule_id

    )

    try:

        rule.active = not rule.active

        log_action(

            f"Prim kuralı {'Aktif' if rule.active else 'Pasif'} yapıldı (#{rule.id})"

        )

        db.session.commit()

        flash(

            "Kural durumu güncellendi.",

            "success"

        )

    except Exception as e:

        db.session.rollback()

        flash(

            str(e),

            "danger"

        )

    return redirect(

        url_for(

            "prime_rules.index"

        )

    )


@prime_rules_bp.route(

    "/delete/<int:rule_id>"

)
@login_required
def delete(

    rule_id

):

    rule = PrimeRule.query.get_or_404(

        rule_id

    )

    try:

        rule.active = False

        log_action(

            f"Prim kuralı pasife alındı (#{rule.id})"

        )

        db.session.commit()

        flash(

            "Prim kuralı pasife alındı.",

            "success"

        )

    except Exception as e:

        db.session.rollback()

        flash(

            str(e),

            "danger"

        )

    return redirect(

        url_for(

            "prime_rules.index"

        )

    )


@prime_rules_bp.route(

    "/copy/<int:rule_id>"

)
@login_required
def copy(

    rule_id

):

    source = PrimeRule.query.get_or_404(

        rule_id

    )

    try:

        new_rule = PrimeRule(

            product_id=source.product_id,

            required_percent=source.required_percent,

            include_in_prime=source.include_in_prime,

            include_in_total_tl=source.include_in_total_tl,

            valid_from=source.valid_from,

            valid_to=source.valid_to,

            active=False

        )

        db.session.add(

            new_rule

        )

        log_action(

            f"Prim kuralı kopyalandı (#{source.id})"

        )

        db.session.commit()

        flash(

            "Prim kuralı başarıyla kopyalandı.",

            "success"

        )

    except Exception as e:

        db.session.rollback()

        flash(

            str(e),

            "danger"

        )

    return redirect(

        url_for(

            "prime_rules.index"

        )

    )


@prime_rules_bp.route(

    "/history/<int:product_id>"

)
@login_required
def history(

    product_id

):

    product = Product.query.get_or_404(

        product_id

    )

    rules = PrimeRule.query.filter_by(

        product_id=product_id

    ).order_by(

        PrimeRule.valid_from.desc(),

        PrimeRule.id.desc()

    ).all()

    return render_template(

        "prime_rule_history.html",

        product=product,

        rules=rules

    )


@prime_rules_bp.route(

    "/activate/<int:rule_id>"

)
@login_required
def activate(

    rule_id

):

    rule = PrimeRule.query.get_or_404(

        rule_id

    )

    try:

        PrimeRule.query.filter(

            PrimeRule.product_id == rule.product_id

        ).update(

            {

                PrimeRule.active: False

            }

        )

        rule.active = True

        log_action(

            f"Prim kuralı aktif edildi (#{rule.id})"

        )

        db.session.commit()

        flash(

            "Aktif prim kuralı güncellendi.",

            "success"

        )

    except Exception as e:

        db.session.rollback()

        flash(

            str(e),

            "danger"

        )

    return redirect(

        url_for(

            "prime_rules.index"

        )
    )
