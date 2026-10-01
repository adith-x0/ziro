from app.config import Settings


def test_settings_defaults():
    """Verify default application configuration values."""
    cfg = Settings()
    assert cfg.service_name == "nexus-backend"
    assert cfg.port == 8000
    assert cfg.safety_gate_strict_mode is True
    assert cfg.flood_surge_threshold_percent == 15.0
    assert len(cfg.cors_origins) >= 1
