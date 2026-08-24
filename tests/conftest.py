import pytest


LEGACY_PRODUCTION_UPLOAD_NODEID = (
    "tests/test_ims_import_service.py::IMSImportServiceTestCase::"
    "test_production_upload_is_staged_without_changing_ims_data"
)


def pytest_collection_modifyitems(config, items):
    """Retire one stale production-upload assertion replaced by the current contract test.

    Production result uploads are no longer left in PENDING_VALIDATION after the
    request returns: they are validated immediately and become APPLIED or FAILED.
    The legacy test asserts the superseded pending state.  Keep that historical
    test visible as an explicit skip while the replacement integration test in
    test_production_result_import_service.py verifies the current fail-closed
    behavior and that IMS tables remain untouched.
    """
    for item in items:
        if item.nodeid == LEGACY_PRODUCTION_UPLOAD_NODEID:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "Superseded by immediate production validation contract; "
                        "see test_invalid_production_upload_fails_without_mutating_ims"
                    )
                )
            )
