import pytest


@pytest.mark.skip(reason='blocked: core.payments events/intents modules not found')
def test_poll_webhook_race():
    pass
