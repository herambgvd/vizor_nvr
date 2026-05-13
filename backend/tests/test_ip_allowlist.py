from app.core.ip_allowlist import _parse_cidrs, _ip_allowed


def test_parse_cidrs():
    cidrs = _parse_cidrs("10.0.0.0/8, 192.168.1.0/24, garbage, 2001:db8::/32")
    # garbage entry dropped
    assert len(cidrs) == 3


def test_ip_allowed_localhost_always():
    assert _ip_allowed("127.0.0.1", [])
    assert _ip_allowed("::1", [])


def test_ip_allowed_match():
    cidrs = _parse_cidrs("10.0.0.0/8")
    assert _ip_allowed("10.5.5.5", cidrs)
    assert not _ip_allowed("11.0.0.1", cidrs)


def test_ip_allowed_invalid():
    assert not _ip_allowed("not-an-ip", _parse_cidrs("10.0.0.0/8"))
    assert not _ip_allowed("", _parse_cidrs("10.0.0.0/8"))
