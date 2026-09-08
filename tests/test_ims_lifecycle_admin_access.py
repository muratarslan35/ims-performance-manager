from types import SimpleNamespace

from app.ims import _can_manage_ims_lifecycle


def _user(email, role="Admin", authenticated=True):
    return SimpleNamespace(email=email, role=role, is_authenticated=authenticated)


def test_only_named_admin_can_manage_destructive_ims_history_actions():
    assert _can_manage_ims_lifecycle(_user("murat.arslan@bilimilac.com"))
    assert _can_manage_ims_lifecycle(_user(" MURAT.ARSLAN@BILIMILAC.COM "))
    assert not _can_manage_ims_lifecycle(_user("other.admin@bilimilac.com"))
    assert not _can_manage_ims_lifecycle(_user("murat.arslan@bilimilac.com", role="Manager"))
    assert not _can_manage_ims_lifecycle(
        _user("murat.arslan@bilimilac.com", authenticated=False)
    )
