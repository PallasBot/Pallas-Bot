"""内核共享 SMTP 邮件传输与凭据配置。"""

from __future__ import annotations

import pallas.core.foundation.config.repo_settings as repo_settings
from pallas.core.shared.utils import mail as mail_mod


def _isolate_env(monkeypatch, env: dict[str, str]) -> None:
    """让 SmtpConfig 只从给定 env 读取（屏蔽磁盘 .env 合并值）。"""
    monkeypatch.setattr(repo_settings, "merged_repo_settings_upper", dict)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    mail_mod.clear_smtp_config_cache()


def test_smtp_config_reads_pallas_smtp_env(monkeypatch):
    _isolate_env(
        monkeypatch,
        {
            "PALLAS_SMTP_USER": "sender@qq.com",
            "PALLAS_SMTP_PASSWORD": "secret-token",
            "PALLAS_SMTP_SERVER": "smtp.qq.com",
            "PALLAS_SMTP_PORT": "465",
        },
    )
    cfg = mail_mod.get_smtp_config()
    assert cfg.smtp_user == "sender@qq.com"
    assert cfg.smtp_password == "secret-token"
    assert cfg.smtp_server == "smtp.qq.com"
    assert cfg.smtp_port == 465
    mail_mod.clear_smtp_config_cache()


def test_build_mail_config_uses_given_recipient(monkeypatch):
    _isolate_env(
        monkeypatch,
        {
            "PALLAS_SMTP_USER": "sender@qq.com",
            "PALLAS_SMTP_PASSWORD": "secret-token",
            "PALLAS_SMTP_SERVER": "smtp.qq.com",
            "PALLAS_SMTP_PORT": "587",
        },
    )
    mail = mail_mod.build_mail_config("player@qq.com")
    assert mail.user == "sender@qq.com"
    assert mail.server == "smtp.qq.com"
    assert mail.port == 587
    assert mail.notice_email == "player@qq.com"
    assert mail.check_params() is True
    mail_mod.clear_smtp_config_cache()


def test_mail_config_check_params_requires_all_fields(monkeypatch):
    _isolate_env(monkeypatch, {"PALLAS_SMTP_USER": "sender@qq.com"})
    # 缺 password/server，凭据不完整
    assert mail_mod.build_mail_config("player@qq.com").check_params() is False
    mail_mod.clear_smtp_config_cache()
