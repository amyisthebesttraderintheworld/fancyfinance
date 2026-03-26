from types import SimpleNamespace

from supabase_client import PRO_MEMBERSHIP, TRIAL_PRO_MEMBERSHIP, SupabaseManager


class _SchemaCacheFallbackClient:
    def __init__(self, trade_fail_column=None, position_fail_column=None):
        self.trade_fail_column = trade_fail_column
        self.position_fail_column = position_fail_column
        self.trade_failed = False
        self.position_failed = False
        self.trade_payloads = []
        self.position_payloads = []

    def table(self, table_name):
        client = self

        class _Operation:
            def insert(self, payload):
                self.payload = dict(payload)
                self.table_name = table_name
                return self

            def upsert(self, payload, on_conflict=None):
                self.payload = dict(payload)
                self.table_name = table_name
                self.on_conflict = on_conflict
                return self

            def execute(self):
                if (
                    self.table_name == "trades"
                    and client.trade_fail_column
                    and client.trade_fail_column in self.payload
                    and not client.trade_failed
                ):
                    client.trade_failed = True
                    raise Exception(
                        f"{{'message': \"Could not find the '{client.trade_fail_column}' column of 'trades' in the schema cache\", 'code': 'PGRST204'}}"
                    )
                if (
                    self.table_name == "positions"
                    and client.position_fail_column
                    and client.position_fail_column in self.payload
                    and not client.position_failed
                ):
                    client.position_failed = True
                    raise Exception(
                        f"{{'message': \"Could not find the '{client.position_fail_column}' column of 'positions' in the schema cache\", 'code': 'PGRST204'}}"
                    )

                if self.table_name == "trades":
                    client.trade_payloads.append(dict(self.payload))
                if self.table_name == "positions":
                    client.position_payloads.append(dict(self.payload))
                return SimpleNamespace(data=[self.payload])

        return _Operation()


def test_complimentary_pro_env_grants_paid_access(monkeypatch):
    monkeypatch.setenv("COMPLIMENTARY_PRO_TELEGRAM_IDS", "12345")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()

    summary = db.get_membership_summary(12345, "tester", "Test")

    assert summary is not None
    assert summary["tier"] == PRO_MEMBERSHIP
    assert summary["status"] == "active"
    assert summary["source"] == "complimentary"
    assert summary["can_simulation"] is True
    assert summary["can_live"] is True


def test_complimentary_pro_env_overrides_manual_free(monkeypatch):
    monkeypatch.setenv("COMPLIMENTARY_PRO_TELEGRAM_IDS", "12345")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()
    db.set_membership(12345, "free")

    summary = db.get_membership_summary(12345, "tester", "Test")

    assert summary is not None
    assert summary["tier"] == PRO_MEMBERSHIP
    assert summary["status"] == "active"
    assert summary["source"] == "complimentary"


def test_zero_knowledge_vault_round_trip(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()

    stored = db.store_user_api_keys(
        12345,
        "pk_live_test",
        "ps_live_test",
        "correct horse battery staple",
        exchange="phemex",
    )
    assert stored is True

    status = db.get_user_api_key_status(12345)
    assert status["configured"] is True
    assert status["zero_knowledge"] is True
    assert status["requires_passphrase"] is True

    creds = db.get_user_api_keys(
        12345,
        passphrase="correct horse battery staple",
        exchange="phemex",
    )
    assert creds == {
        "api_key": "pk_live_test",
        "api_secret": "ps_live_test",
    }


def test_find_user_by_email_matches_case_insensitively(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()
    user = db.get_or_create_user(12345, "tester", "Test")
    user["email"] = "user@example.com"

    matched = db.find_user_by_email("USER@EXAMPLE.COM")

    assert matched is not None
    assert matched["telegram_id"] == 12345


def test_zero_knowledge_vault_rejects_wrong_passphrase(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()
    db.store_user_api_keys(
        12345,
        "pk_live_test",
        "ps_live_test",
        "correct horse battery staple",
        exchange="phemex",
    )

    creds = db.get_user_api_keys(
        12345,
        passphrase="wrong passphrase",
        exchange="phemex",
    )
    assert creds is None


def test_start_trial_membership_grants_trial_pro_access(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()
    db.start_trial_membership(12345, days=7, username="tester", first_name="Test")

    summary = db.get_membership_summary(12345, "tester", "Test")

    assert summary is not None
    assert summary["tier"] == TRIAL_PRO_MEMBERSHIP
    assert summary["status"] == "trial_pro"
    assert summary["can_simulation"] is True
    assert summary["can_live"] is True
    assert summary["expires_at"] is not None


def test_log_trade_retries_without_missing_optional_column(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()
    db.client = _SchemaCacheFallbackClient(trade_fail_column="leverage")

    stored = db.log_trade(
        {
            "symbol": "BTCUSD",
            "direction": "long",
            "type": "entry",
            "price": 40000.0,
            "qty": 0.1,
            "leverage": 5,
        },
        user_id=12345,
    )

    assert stored is True
    assert db.client.trade_payloads
    assert "leverage" not in db.client.trade_payloads[-1]
    assert db.client.trade_payloads[-1]["user_id"] == 12345
    assert "leverage" in db._unsupported_trade_columns


def test_update_position_retries_without_missing_optional_column(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()
    db.client = _SchemaCacheFallbackClient(position_fail_column="leverage")

    stored = db.update_position(
        "BTCUSD",
        {
            "direction": "long",
            "entry_price": 40000.0,
            "qty": 0.1,
            "leverage": 5,
            "margin_used": 10.0,
        },
        user_id=12345,
    )

    assert stored is True
    assert db.client.position_payloads
    assert "leverage" not in db.client.position_payloads[-1]
    assert db.client.position_payloads[-1]["user_id"] == 12345
    assert "leverage" in db._unsupported_position_columns


def test_user_config_envelope_preserves_strategy_and_simulation_state(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    db = SupabaseManager()

    assert db.store_user_strategy_config(12345, {"timeframe": "15m", "leverage": 5}) is True
    assert db.store_user_simulation_state(
        12345,
        {
            "balance": 98.5,
            "reference_balance": 100.0,
            "session_started_at": "2026-03-25T20:00:00+00:00",
        },
    ) is True

    assert db.get_user_strategy_config(12345) == {"timeframe": "15m", "leverage": 5}
    assert db.get_user_simulation_state(12345) == {
        "balance": 98.5,
        "reference_balance": 100.0,
        "session_started_at": "2026-03-25T20:00:00+00:00",
    }
    assert db.list_user_ids_with_simulation_state() == [12345]
