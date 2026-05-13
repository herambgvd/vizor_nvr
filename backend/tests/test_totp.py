import time
from app.auth import totp_service


def test_generate_secret_is_base32():
    s = totp_service.generate_secret()
    assert len(s) >= 32
    # Base32 alphabet: A-Z 2-7
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in s)


def test_current_code_verifies():
    s = totp_service.generate_secret()
    code = totp_service.current_code(s)
    assert totp_service.verify(s, code)


def test_wrong_code_rejected():
    s = totp_service.generate_secret()
    assert not totp_service.verify(s, "000000")


def test_provisioning_uri_format():
    uri = totp_service.provisioning_uri("alice", "JBSWY3DPEHPK3PXP")
    assert uri.startswith("otpauth://totp/GVD%20NVR:alice?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
