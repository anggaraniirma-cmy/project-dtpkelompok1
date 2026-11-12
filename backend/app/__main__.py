"""Jalankan backend API: python -m app.main / scripts/run_all.py"""
from __future__ import annotations

import argparse

import uvicorn

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(description="SKOMDA Gesture Quiz — backend API")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--reload", action="store_true", help="Mode development")
    args = parser.parse_args()

    print(f"\n  SKOMDA Gesture Quiz API  ->  http://{args.host}:{args.port}")
    print(f"  Dokumentasi API          ->  http://{args.host}:{args.port}/docs\n")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
