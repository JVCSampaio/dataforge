from dataforge.config import load_settings


def test_settings_read_quality_and_user_env(monkeypatch):
    monkeypatch.setenv("QUALITY_MAX_AGE_HOURS", "12")
    monkeypatch.setenv("QUALITY_ROW_DROP_RATIO", "0.25")
    monkeypatch.setenv("QUALITY_REPORT_DIR", "reports")
    monkeypatch.setenv("GITHUB_USERS", "octocat, ,jakevdp")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    settings = load_settings()
    assert settings.quality_max_age_hours == 12
    assert settings.quality_row_drop_ratio == 0.25
    assert settings.quality_report_dir == "reports"
    assert settings.github_users == ["octocat", "jakevdp"]
    assert settings.github_token is None
