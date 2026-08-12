from pallas.core.foundation.loop import install_uvloop
from pallas.core.runtime import apply_repo_settings, boot

install_uvloop()
apply_repo_settings()

# ruff: noqa: E402
boot()

if __name__ == "__main__":
    import nonebot

    nonebot.run()
