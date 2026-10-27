"""Command-line intake for the GRC Assurance Engine.

Run with ``python -m app.cli``. The commands call the same intake builder and
risk engine as the public form. They print JSON to stdout. They write to the
risk register only when ``--persist`` is set, or the JSON request sets
``persist`` to true, together with a human disposition and rationale.

Exit codes:

- 0: an assessment was produced, or a file preview can be assessed
- 2: the request or file failed validation
- 1: the engine raised an unexpected error
"""

import argparse
import json
import sys
from contextlib import contextmanager
from pathlib import Path

from app.services.bot_intake import (
    BotRequestError, assess_file, assess_request, error_document, load_json_object,
    parse_cli_date, preview_document, preview_file,
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
            payload = _merge_persist_flags(load_json_object(_read_text(args.path)), args)
            will_persist = isinstance(payload, dict) and payload.get("persist") is True
            with _database_for(will_persist) as db:
                _emit(assess_request(payload, db=db))
            return EXIT_OK
        as_of = parse_cli_date(args.as_of)
        data = _read_bytes(args.path)
        filename = Path(args.path).name
        if args.command == "preview":
            document = preview_file(filename, data, as_of)
            _emit(document)
            return EXIT_OK if document["can_assess"] else EXIT_VALIDATION
        decision = _file_decision(args)
        with _database_for(decision is not None) as db:
            _emit(assess_file(filename, data, as_of, decision=decision, db=db))
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
            "Results come from the risk engine. Nothing is saved unless --persist is set "
            "or the JSON request sets persist to true, with a human disposition and rationale."
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
    _add_persist_flags(assess)

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
    _add_persist_flags(assess_file)
    return parser


def _add_persist_flags(parser):
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Save the assessed vendor or vendors. Requires a disposition, rationale, and decider.",
    )
    parser.add_argument(
        "--disposition",
        help="Human disposition: approve, approve_with_conditions, escalate, or reject.",
    )
    parser.add_argument("--rationale", help="Short rationale for the human disposition.")
    parser.add_argument("--decider", help="Name or role of the person deciding.")
    parser.add_argument(
        "--conditions",
        default="",
        help="Stored only for approve_with_conditions.",
    )
    parser.add_argument(
        "--exception-rationale",
        dest="exception_rationale",
        default="",
        help="Required only when approving a prohibited result.",
    )
    parser.add_argument(
        "--handling-minutes",
        dest="handling_minutes",
        default=None,
        help=(
            "Optional self-reported minutes spent reviewing. "
            "Omit the flag, or leave it blank, to leave handling time unmeasured."
        ),
    )
    parser.add_argument(
        "--rework-minutes",
        dest="rework_minutes",
        default=None,
        help=(
            "Optional self-reported minutes spent redoing work after a first pass. "
            "Omit the flag, or leave it blank, to leave rework time unmeasured. "
            "This is not handling time."
        ),
    )


def _flags_used(args):
    return bool(
        args.persist or args.disposition or args.rationale or args.decider
        or args.conditions or args.exception_rationale or args.handling_minutes
        or args.rework_minutes
    )


def _decision_from_flags(args):
    decision = {
        "disposition": args.disposition or "",
        "rationale": args.rationale or "",
        "decider": args.decider or "",
        "conditions": args.conditions or "",
        "exception_rationale": args.exception_rationale or "",
    }
    if args.handling_minutes is not None:
        decision["handling_minutes"] = args.handling_minutes
    if args.rework_minutes is not None:
        decision["rework_minutes"] = args.rework_minutes
    return decision


def _merge_persist_flags(payload, args):
    """Apply CLI persist flags onto an assess request. Flags and JSON do not mix."""
    if not _flags_used(args):
        return payload
    if not args.persist:
        raise BotRequestError(["Disposition flags require --persist. Nothing was saved."])
    if isinstance(payload, dict) and ("persist" in payload or "decision" in payload):
        raise BotRequestError([
            "Use either the JSON persist fields or the CLI persist flags, not both. Nothing was saved.",
        ])
    if not isinstance(payload, dict):
        return payload
    merged = dict(payload)
    merged["persist"] = True
    merged["decision"] = _decision_from_flags(args)
    return merged


def _file_decision(args):
    if not _flags_used(args):
        return None
    if not args.persist:
        raise BotRequestError(["Disposition flags require --persist. Nothing was saved."])
    return _decision_from_flags(args)


@contextmanager
def _database_for(needed):
    """Open the application database only when a confirmed save will run."""
    if not needed:
        yield None
        return
    from app import create_app
    from app.db import get_db

    app = create_app()
    with app.app_context():
        yield get_db()


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
