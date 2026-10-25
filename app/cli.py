"""Command-line intake for the GRC Assurance Engine.

Run with ``python -m app.cli``. The commands call the same intake builder and
risk engine as the public form. They print JSON to stdout and do not write to
the risk register.

Exit codes:

- 0: an assessment was produced, or a file preview can be assessed
- 2: the request or file failed validation
- 1: the engine raised an unexpected error
"""

import argparse
import json
import sys
from pathlib import Path

from app.services.bot_intake import (
    BotRequestError, assess_file, assess_request_text, error_document, parse_cli_date,
    preview_document, preview_file,
)

EXIT_OK = 0
EXIT_ENGINE = 1
EXIT_VALIDATION = 2


def main(argv=None):
    """Run one CLI command and return its exit code."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = EXIT_VALIDATION if exc.code is None else exc.code
        return code

    try:
        if args.command == "assess":
            _emit(assess_request_text(_read_text(args.path)))
            return EXIT_OK
        as_of = parse_cli_date(args.as_of)
        data = _read_bytes(args.path)
        filename = Path(args.path).name
        if args.command == "preview":
            document = preview_file(filename, data, as_of)
            _emit(document)
            return EXIT_OK if document["can_assess"] else EXIT_VALIDATION
        _emit(assess_file(filename, data, as_of))
        return EXIT_OK
    except BotRequestError as exc:
        if exc.preview is not None:
            _emit(preview_document(exc.preview))
        else:
            _emit(error_document("validation", exc.problems))
        return EXIT_VALIDATION
    except Exception as exc:
        _emit(error_document("engine", [f"{type(exc).__name__}: {exc}"]))
        return EXIT_ENGINE


def _parser():
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description=(
            "Run a synthetic vendor intake without the web UI. "
            "Results come from the risk engine. Nothing is saved."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    assess = commands.add_parser("assess", help="Assess one vendor from a JSON request.")
    assess.add_argument(
        "path",
        nargs="?",
        default="-",
        help="Path to the JSON request. Use - to read stdin.",
    )

    preview = commands.add_parser(
        "preview",
        help="Parse a CSV, .xlsx, or simulated ServiceNow file. Does not score.",
    )
    preview.add_argument("path", help="Intake file to parse.")
    preview.add_argument("--as-of", dest="as_of", help="Evaluation date, YYYY-MM-DD. Default is today.")

    assess_file = commands.add_parser(
        "assess-file",
        help="Assess every row in an intake file when the whole file is valid.",
    )
    assess_file.add_argument("path", help="Intake file to assess.")
    assess_file.add_argument("--as-of", dest="as_of", help="Evaluation date, YYYY-MM-DD. Default is today.")
    return parser


def _emit(document):
    json.dump(document, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _read_text(path):
    if path == "-":
        if getattr(sys.stdin, "isatty", lambda: False)():
            raise BotRequestError(["Pass a JSON file, or pipe a JSON request on stdin."])
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise BotRequestError([_read_problem(path, exc)]) from exc
    except UnicodeDecodeError as exc:
        raise BotRequestError(["The request file is not UTF-8 text."]) from exc


def _read_bytes(path):
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise BotRequestError([_read_problem(path, exc)]) from exc


def _read_problem(path, exc):
    detail = exc.strerror or str(exc)
    return f"Could not read {path}: {detail}."


if __name__ == "__main__":
    sys.exit(main())
