"""Secrets manager, encryption and redaction."""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from packages.infrastructure.config_manager import ConfigurationError
from packages.infrastructure.key_vault import SecretsManager, mask, redact_text
from packages.infrastructure.key_vault import crypto
from packages.infrastructure.key_vault.store import DbKeyStore, KeyRecord
from packages.infrastructure.log_redaction import RedactingFilter

from .conftest import FAKE_KEY_A, FAKE_KEY_B, FAKE_KEY_C


class FakeStore:
    """In-memory stand-in for DbKeyStore."""

    def __init__(self, keys=None):
        self.keys = list(keys or [])
        self.failed = []
        self.used = []

    def usable_keys(self, provider):
        return [k for k in self.keys if k.provider == provider]

    def mark_failed(self, key_id, status_code, cooldown_s):
        self.failed.append((key_id, status_code, cooldown_s))
        if status_code in (401, 403, 429):
            self.keys = [k for k in self.keys if k.id != key_id]

    def mark_used(self, key_id):
        self.used.append(key_id)

    def add_key(self, provider, value, **kw):
        kid = f"db-{len(self.keys)}"
        self.keys.append(KeyRecord(id=kid, provider=provider, value=value, priority=kw.get("priority", 100)))
        return kid


def _db_key(i, value, priority=100):
    return KeyRecord(id=f"db-{i}", provider="groq", value=value, priority=priority, source="db")


# ── crypto ───────────────────────────────────────────────────────────────────

def test_encrypt_decrypt_round_trip():
    token = crypto.encrypt(FAKE_KEY_A)
    assert token != FAKE_KEY_A and FAKE_KEY_A not in token
    assert crypto.decrypt(token) == FAKE_KEY_A


def test_missing_master_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("SECRETS_MASTER_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="SECRETS_MASTER_KEY"):
        crypto.encrypt("x")


def test_decrypt_with_wrong_master_key_raises(monkeypatch):
    from cryptography.fernet import Fernet
    token = crypto.encrypt(FAKE_KEY_A)
    monkeypatch.setenv("SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    with pytest.raises(ConfigurationError):
        crypto.decrypt(token)


# ── redaction ────────────────────────────────────────────────────────────────

def test_mask_shows_only_last_four():
    assert mask(FAKE_KEY_A) == "****aaaa"
    assert mask("abc") == "****"
    assert mask(None) == ""


def test_redact_text_masks_groq_and_aws_keys():
    text = "using gsk_abcdefghijklmnopqrstuvwxyz123456 and AKIAABCDEFGHIJKLMNOP now"
    out = redact_text(text)
    assert "gsk_abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "AKIAABCDEFGHIJKLMNOP" not in out
    assert out.count("[REDACTED]") == 2


def test_logging_filter_scrubs_message_and_args():
    record = logging.LogRecord("t", logging.WARNING, __file__, 1,
                               "key=%s", ("gsk_abcdefghijklmnopqrstuvwxyz123456",), None)
    RedactingFilter().filter(record)
    assert "gsk_abcdefghijklmnopqrstuvwxyz123456" not in record.getMessage()


def test_installed_redaction_protects_real_log_output(caplog):
    import io
    from packages.infrastructure.log_redaction import install_redaction
    install_redaction()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)  # created after install -> filter attached automatically
    log = logging.getLogger("redaction-probe")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.info("token gsk_abcdefghijklmnopqrstuvwxyz123456")
    assert "gsk_abcdefghijklmnopqrstuvwxyz123456" not in stream.getvalue()
    assert "[REDACTED]" in stream.getvalue()


def test_keyrecord_repr_never_contains_value():
    rec = KeyRecord(id="x", provider="groq", value=FAKE_KEY_A)
    assert FAKE_KEY_A not in repr(rec) and FAKE_KEY_A not in str(rec)


# ── selection and rotation ───────────────────────────────────────────────────

def test_no_keys_returns_none():
    assert SecretsManager(db_store=FakeStore()).get_active_key("groq") is None


def test_db_key_beats_env_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY_B)
    mgr = SecretsManager(db_store=FakeStore([_db_key(0, FAKE_KEY_A)]))
    assert mgr.get_active_key("groq").value == FAKE_KEY_A


def test_env_keys_list_supported(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEYS", f"{FAKE_KEY_A}, {FAKE_KEY_B}")
    mgr = SecretsManager(db_store=FakeStore())
    assert mgr.get_active_key("groq").value == FAKE_KEY_A


def test_priority_orders_db_keys():
    store = FakeStore([_db_key(0, FAKE_KEY_A, priority=50), _db_key(1, FAKE_KEY_B, priority=10)])
    assert SecretsManager(db_store=store).get_active_key("groq").value == FAKE_KEY_B


def test_429_puts_env_key_in_cooldown_and_next_key_is_used(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEYS", f"{FAKE_KEY_A},{FAKE_KEY_B}")
    now = [1000.0]
    mgr = SecretsManager(db_store=FakeStore(), clock=lambda: now[0])
    first = mgr.get_active_key("groq")
    mgr.report_failure(first, 429, retry_after=30)
    assert mgr.get_active_key("groq").value == FAKE_KEY_B
    # after the cooldown the first key is usable again
    now[0] += 31
    mgr.invalidate_cache()
    assert mgr.get_active_key("groq").value == FAKE_KEY_A


def test_401_marks_env_key_invalid_permanently(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEYS", f"{FAKE_KEY_A},{FAKE_KEY_B}")
    now = [0.0]
    mgr = SecretsManager(db_store=FakeStore(), clock=lambda: now[0])
    first = mgr.get_active_key("groq")
    mgr.report_failure(first, 401)
    now[0] += 10_000
    mgr.invalidate_cache()
    assert mgr.get_active_key("groq").value == FAKE_KEY_B


def test_failure_on_db_key_is_recorded_in_store():
    store = FakeStore([_db_key(0, FAKE_KEY_A), _db_key(1, FAKE_KEY_B, priority=200)])
    mgr = SecretsManager(db_store=store)
    key = mgr.get_active_key("groq")
    mgr.report_failure(key, 429, retry_after=12)
    assert store.failed == [("db-0", 429, 12)]
    assert mgr.get_active_key("groq").value == FAKE_KEY_B


def test_5xx_does_not_penalise_env_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY_A)
    mgr = SecretsManager(db_store=FakeStore())
    key = mgr.get_active_key("groq")
    mgr.report_failure(key, 503)
    assert mgr.get_active_key("groq").value == FAKE_KEY_A


def test_least_recently_used_env_key_is_preferred_among_equals():
    store = FakeStore([_db_key(0, FAKE_KEY_A), _db_key(1, FAKE_KEY_B)])
    mgr = SecretsManager(db_store=store)
    first = mgr.get_active_key("groq")
    mgr.mark_used(first)
    assert mgr.get_active_key("groq").value != first.value


def test_new_key_is_visible_without_restart():
    store = FakeStore()
    mgr = SecretsManager(db_store=store)
    assert mgr.get_active_key("groq") is None
    mgr.add_key("groq", FAKE_KEY_C)
    assert mgr.get_active_key("groq").value == FAKE_KEY_C


def test_aws_backend_reads_secrets_when_enabled(monkeypatch):
    monkeypatch.setenv("USE_AWS_SECRETS", "true")
    from packages.infrastructure.config_manager import config_manager
    monkeypatch.setattr(config_manager, "_fetch_aws_secrets", lambda: {"GROQ_API_KEY": FAKE_KEY_C})
    key = SecretsManager(db_store=FakeStore()).get_active_key("groq")
    assert key.value == FAKE_KEY_C and key.source == "aws"


def test_aws_backend_ignored_when_disabled(monkeypatch):
    from packages.infrastructure.config_manager import config_manager
    monkeypatch.setattr(config_manager, "_fetch_aws_secrets", lambda: {"GROQ_API_KEY": FAKE_KEY_C})
    assert SecretsManager(db_store=FakeStore()).get_active_key("groq") is None


def test_broken_db_store_falls_back_to_env(monkeypatch):
    class Broken:
        def usable_keys(self, provider):
            raise RuntimeError("db down")
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY_A)
    assert SecretsManager(db_store=Broken()).get_active_key("groq").value == FAKE_KEY_A


# ── real PostgreSQL store ────────────────────────────────────────────────────

def test_db_store_encrypts_at_rest_and_lists_masked(db, cursor_ctx):
    store = DbKeyStore(cursor_ctx)
    kid = store.add_key("groq", FAKE_KEY_A, label="daily", priority=5)
    with db.cursor() as cur:
        cur.execute("SELECT ciphertext, last4 FROM ops_dataextraction.api_keys WHERE id = %s::uuid", (kid,))
        ciphertext, last4 = cur.fetchone()
    assert FAKE_KEY_A not in ciphertext and not ciphertext.startswith("gsk_")
    assert last4 == "aaaa"
    listing = store.list_keys("groq")
    assert listing[0]["masked"] == "****aaaa"
    assert all("ciphertext" not in row and FAKE_KEY_A not in str(row) for row in listing)
    assert store.usable_keys("groq")[0].value == FAKE_KEY_A


def test_db_store_skips_expired_cooldown_invalid_and_disabled(db, cursor_ctx):
    store = DbKeyStore(cursor_ctx)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = store.add_key("groq", FAKE_KEY_A, expires_at=past)
    cooling = store.add_key("groq", FAKE_KEY_B)
    invalid = store.add_key("groq", FAKE_KEY_C)
    disabled = store.add_key("groq", "gsk_test_fake_key_3333_dddddddd")
    good = store.add_key("groq", "gsk_test_fake_key_4444_eeeeeeee")
    store.mark_failed(cooling, 429, 600)
    store.mark_failed(invalid, 401, 0)
    store.update_key(disabled, status="disabled")
    usable = store.usable_keys("groq")
    assert [k.id for k in usable] == [good]
    assert {expired, cooling, invalid, disabled}.isdisjoint({k.id for k in usable})


def test_db_store_reactivating_a_key_clears_failure_state(db, cursor_ctx):
    store = DbKeyStore(cursor_ctx)
    kid = store.add_key("groq", FAKE_KEY_A)
    store.mark_failed(kid, 401, 0)
    assert store.usable_keys("groq") == []
    store.update_key(kid, status="active")
    assert [k.id for k in store.usable_keys("groq")] == [kid]


def test_manager_with_real_store_picks_up_newly_added_key(db, cursor_ctx):
    mgr = SecretsManager(db_store=DbKeyStore(cursor_ctx))
    assert mgr.get_active_key("groq") is None
    mgr.add_key("groq", FAKE_KEY_A, label="monday")
    assert mgr.get_active_key("groq").value == FAKE_KEY_A
    mgr.add_key("groq", FAKE_KEY_B, label="tuesday", priority=1)
    assert mgr.get_active_key("groq").value == FAKE_KEY_B


def test_empty_key_rejected(db, cursor_ctx):
    with pytest.raises(ValueError):
        DbKeyStore(cursor_ctx).add_key("groq", "   ")
