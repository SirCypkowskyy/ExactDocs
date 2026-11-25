from app.settings import ServerSettings


def test_settings_hold_host_and_port():
    settings = ServerSettings(host="localhost", port=8000)
    assert (settings.host, settings.port) == ("localhost", 8000)
