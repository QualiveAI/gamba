from core.catalog.rtp import validate_catalog


def test_rtp_gate():
    report = validate_catalog(
        [{"nominal_units": 10, "real_value_minor": 10, "weight_bp": 10000}], "units", 9000
    )  # noqa: E501
    assert "errors" in report
