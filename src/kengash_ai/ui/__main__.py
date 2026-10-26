"""`python -m kengash_ai.ui --port N`: serve the UI on 127.0.0.1; the token comes from
`HARNESS_UI_TOKEN`, never the command line (other users can read argv)."""

import argparse
import os
import sys

import uvicorn

from kengash_ai.ui.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kengash_ai.ui")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    token = os.environ.pop("HARNESS_UI_TOKEN", "")
    if not token:
        print("HARNESS_UI_TOKEN is not set", file=sys.stderr)
        return 2
    app = create_app(token=token, port=args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
