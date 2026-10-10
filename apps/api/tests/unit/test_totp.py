import base64

from app.core import totp

# RFC 6238 Appendix B (SHA-1 seed "12345678901234567890"), last 6 digits.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


def test_rfc6238_vectors() -> None:
    for t, expected in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924")):
        assert totp.code_at(RFC_SECRET, t // 30) == expected


def test_verify_window_and_replay() -> None:
    secret = totp.new_secret()
    now = 1_700_000_000.0
    step = totp.current_step(now)
    code = totp.code_at(secret, step)
    assert totp.verify(secret, code, last_used_step=0, now=now) == step
    # Same code again (replay) is refused once its step was used.
    assert totp.verify(secret, code, last_used_step=step, now=now) is None
    # Adjacent steps are accepted for drift, older ones are not.
    assert (
        totp.verify(secret, totp.code_at(secret, step - 1), last_used_step=0, now=now) == step - 1
    )
    assert totp.verify(secret, totp.code_at(secret, step - 2), last_used_step=0, now=now) is None
    for bad in ("", "12345", "abcdef", "1234567"):
        assert totp.verify(secret, bad, last_used_step=0, now=now) is None
