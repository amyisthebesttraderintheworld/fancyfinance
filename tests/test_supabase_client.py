from supabase_client import PRO_MEMBERSHIP, TRIAL_PRO_MEMBERSHIP, SupabaseManager


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
