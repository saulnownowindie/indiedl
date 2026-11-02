"""Indie Now DL - punto de entrada."""
import os
import sys

from indiedl_core import log, register
from indiedl_ui import build_app


def main():
    if "--register-only" in sys.argv:
        try:
            if os.name == "nt":
                register()
                log("Protocolo ytdl:// registrado por el instalador.")
        except Exception as e:
            log(f"No se pudo registrar ytdl://: {e}")
        return 0
    build_app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
