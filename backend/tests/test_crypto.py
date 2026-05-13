from app.core.crypto import encrypt_value, decrypt_value, is_encrypted, reset_cipher_cache


def setup_function(_):
    reset_cipher_cache()


def test_encrypt_roundtrip():
    out = encrypt_value("admin")
    assert out.startswith("enc:")
    assert is_encrypted(out)
    assert decrypt_value(out) == "admin"


def test_encrypt_idempotent():
    enc1 = encrypt_value("secret123")
    enc2 = encrypt_value(enc1)
    assert enc1 == enc2


def test_decrypt_plaintext_passthrough():
    # Legacy plaintext rows pass through unchanged (no 'enc:' prefix)
    assert decrypt_value("plain") == "plain"


def test_empty_passthrough():
    assert encrypt_value("") == ""
    assert encrypt_value(None) is None
    assert decrypt_value("") == ""
