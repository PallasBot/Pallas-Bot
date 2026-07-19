from pallas.core.runtime import apply_repo_settings, boot

apply_repo_settings()

# ruff: noqa: E402
boot()

if __name__ == "__main__":
    import nonebot

    nonebot.run()
