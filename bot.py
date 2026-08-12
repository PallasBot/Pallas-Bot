from pallas.core.foundation.loop import install_uvloop
from pallas.core.runtime import apply_repo_settings, boot

install_uvloop()
apply_repo_settings()

# ruff: noqa: E402
boot()

if __name__ == "__main__":
    from pallas.core.foundation.asgi_runner import run_asgi_server

    run_asgi_server()
