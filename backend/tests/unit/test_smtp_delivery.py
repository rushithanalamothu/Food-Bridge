import pytest

from foodbridge.integrations.email import SMTPNotifications
from foodbridge.settings import Settings


class SMTP:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def starttls(self, **kwargs):
        self.calls.append("tls")

    def login(self, *args):
        self.calls.append("login")

    def send_message(self, message):
        self.message = message
        self.calls.append("send")
        return {}


def test_smtp_uses_tls_auth_and_stable_message_identity(monkeypatch):
    smtp = SMTP()
    settings = Settings(
        _env_file=None,
        ai_provider="rules",
        notification_mode="smtp",
        smtp_host="mail.example.test",
        smtp_username="service",
        smtp_password="private",
        smtp_allowed_domains=["example.test"],
    )
    adapter = SMTPNotifications(settings, smtp_factory=lambda *a, **kw: smtp)
    monkeypatch.setattr(adapter, "destination", lambda *a: "recipient@example.test")
    identifier = "11111111-1111-4111-8111-111111111111"
    receipt = adapter.send(
        notification_id=identifier, destination_id=identifier, template="donation.reserved.v1"
    )
    assert smtp.calls == ["tls", "login", "send"]
    assert identifier in receipt
    assert str(smtp.message["To"]) == "recipient@example.test"
    assert "private" not in smtp.message.as_string()


def test_smtp_domain_allowlist_is_checked_before_connection(monkeypatch):
    settings = Settings(
        _env_file=None,
        ai_provider="rules",
        notification_mode="smtp",
        smtp_host="mail.example.test",
        smtp_allowed_domains=["example.test"],
    )
    adapter = SMTPNotifications(
        settings, smtp_factory=lambda *a, **kw: pytest.fail("must not connect")
    )
    monkeypatch.setattr(adapter, "destination", lambda *a: "recipient@other.test")
    with pytest.raises(ValueError, match="domain_not_allowed"):
        adapter.send(
            notification_id="11111111-1111-4111-8111-111111111111",
            destination_id="unused",
            template="test",
        )
