import pytest
from sqlalchemy.orm.exc import DetachedInstanceError

from app.extensions import db
from app.models import Product
from app.services.alias_service import AliasService


def test_alias_cache_requires_job_boundary_refresh(app):
    with app.app_context():
        product = Product(
            product_code="CACHE-DETACHED",
            product_name="CACHE DETACHED",
            ims_name="CACHE DETACHED",
            is_active=True,
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

        AliasService.clear_cache()
        first = AliasService.find_product("CACHE DETACHED")["object"]
        assert first.id == product_id

        # Reproduce the long-lived worker failure: cached ORM objects survive
        # beyond the session that loaded them and later need an attribute
        # refresh while detached.
        db.session.expire(first)
        db.session.remove()
        with pytest.raises(DetachedInstanceError):
            _ = first.id

        AliasService.clear_cache()
        second = AliasService.find_product("CACHE DETACHED")["object"]
        assert second.id == product_id
