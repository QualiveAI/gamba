import pytest
from test_environment import validate_test_database_url


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "postgresql://caseplatform:local@127.0.0.1:5432/caseplatform",
        "postgresql://postgres:local@127.0.0.1:55432/windrop_test",
        "dbname=windrop_test user=windrop_test service=production",
    ],
)
def test_refuses_unsafe_database(dsn):
    with pytest.raises(ValueError):
        validate_test_database_url(dsn)


def test_accepts_explicit_test_database_and_role():
    config = validate_test_database_url(
        "postgresql://windrop_test:local@127.0.0.1:55432/windrop_test"
    )
    assert config["dbname"] == "windrop_test"
    assert config["user"] == "windrop_test"
