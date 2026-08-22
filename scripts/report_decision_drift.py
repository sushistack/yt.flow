"""Decision-vs-shipping-default drift for every field in ``config.DECISIONS`` — Story 13.6 AC2/AC3.

Answers the one question `Settings()` cannot: **where did this value come from?**
Pydantic resolves env over default silently and keeps no provenance, so a judged
decision reverted by a stale `YTFLOW_*` pin looks identical to one that shipped
(`gotcha_env-file-beats-code-default`), and a decision that only ever reached
`.env` never ships at all (`gotcha_a-decision-that-only-reaches-env-never-ships`).

WHAT IT REFUSES TO DO:

* **It is not a gate.** A successful read always exits 0, however much drift it
  finds. Half these flags are legitimately off pending live evidence, and a build
  that failed on a non-empty report would be worse than the disease (13.6 Dev
  Notes trap 2). Only a usage error exits non-zero, from argparse.
* **It does not fix anything.** A row here is a finding for the story that owns
  the feature, never for whoever ran the report (13.6 AC5).
* **It does not decide anything.** `DECISIONS` is an index into the dated verdict
  comments in `config.py`; if a row and the comment disagree, the comment wins and
  the row is stale.

THE SOURCE ORDER IS THE WHOLE CLAIM TO HONESTY: `os.environ` > the `.env` named by
``Settings.model_config["env_file"]`` > the code default. Those are the only two
external sources this app configures today (`secrets_dir` is None, nothing passes
init kwargs). If `Settings` ever grows a third, this script must grow with it or
start lying.

Usage:
    uv run python scripts/report_decision_drift.py
    uv run python scripts/report_decision_drift.py --env-file /path/to/.env
"""

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dotenv import dotenv_values  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

from yt_flow.config import DECISIONS, Settings  # noqa: E402

# `.get` not `[...]`: SettingsConfigDict marks both keys NotRequired, so indexing is a
# type error even though this Settings sets them. The defaults mirror config.py:29-33.
_PREFIX = Settings.model_config.get("env_prefix") or ""
# `.env.example` is the file a fresh checkout copies, so a pin in it is a REVERT
# that has not happened yet — reported separately from effective drift because
# nothing on this box is currently wrong.
_EXAMPLE_SUFFIX = ".example"


def _typed(name: str, raw: str) -> object:
    """Parse an env string the way pydantic-settings will, for a like-for-like compare.

    An unparseable pin is returned as the raw string rather than raised: pydantic
    would reject it at startup, which is a louder failure than this report, and a
    report that dies on one bad row hides the other eight.
    """
    try:
        return TypeAdapter(Settings.model_fields[name].annotation).validate_strings(raw)
    except Exception:  # noqa: BLE001 — see docstring; the value is still worth printing
        return raw


def _lower_keys(values: Mapping[str, str | None]) -> dict[str, str]:
    """`case_sensitive: False` in model_config, so pydantic matches case-insensitively."""
    return {k.lower(): v for k, v in values.items() if v is not None}


def _read_env(path: Path) -> tuple[dict[str, str], str]:
    """Values plus a one-word state, so the printer can say ABSENT/UNREADABLE rather
    than silently reporting an empty file as "nothing pinned here" — the difference
    between "checked, clean" and "could not check" is this script's whole job.

    A missing file is dotenv's own documented `{}`; a 0600 file owned by someone else,
    or one with non-UTF-8 bytes, would otherwise raise straight through a tool whose
    contract is that only argparse exits non-zero.
    """
    if not path.is_file():
        return {}, "ABSENT"
    try:
        return _lower_keys(dotenv_values(path)), "present"
    except (OSError, UnicodeDecodeError) as exc:
        return {}, f"UNREADABLE ({type(exc).__name__})"


def collect(environ: Mapping[str, str], env_file: Path, example_file: Path) -> dict[str, list[dict]]:
    """Three buckets plus stale rows, plus `all` — every declared field with its
    resolved source. `all` exists because "no drift" is only believable if the
    report will also say, per field, which of the three sources actually won.

    `state` carries one row naming what each file actually was, so an ABSENT or
    UNREADABLE file cannot be printed as an empty-and-therefore-clean one.
    """
    env_values, env_state = _read_env(env_file)
    example_values, example_state = _read_env(example_file)
    os_values = _lower_keys(environ)

    out: dict[str, list[dict]] = {"drift": [], "env_sourced": [], "latent": [], "stale": [],
                                  "all": [],
                                  "state": [{"env_file": str(env_file), "env_state": env_state,
                                             "example_file": str(example_file),
                                             "example_state": example_state}]}
    for name, decision in DECISIONS.items():
        field = Settings.model_fields.get(name)
        if field is None:
            # A renamed or deleted field. Reported, not raised: this script's only job
            # is being believed, and a KeyError would take the other rows down with it.
            out["stale"].append({"field": name, "story": decision.story, "date": decision.date,
                                 "why": "names no Settings field"})
            continue
        if field.is_required():
            # No default means no "shipping default" to drift FROM: the row would print
            # PydanticUndefined as both effective and default forever. Stale, not drift.
            out["stale"].append({"field": name, "story": decision.story, "date": decision.date,
                                 "why": "required field has no shippable default"})
            continue
        key = f"{_PREFIX}{name}".lower()
        if key in os_values:
            effective, source = _typed(name, os_values[key]), "os.environ"
        elif key in env_values:
            effective, source = _typed(name, env_values[key]), str(env_file)
        else:
            effective, source = field.default, "code default"

        row = {
            "field": name, "story": decision.story, "date": decision.date,
            "decided": decision.decided, "default": field.default,
            "effective": effective, "source": source, "citation": decision.citation,
        }
        out["all"].append(row)
        if effective != decision.decided:
            out["drift"].append(row)
        if source != "code default":
            out["env_sourced"].append(row)  # AC3: named even when the value matches
        if key in example_values:
            # PRESENCE, not difference. Comparing against `field.default` was wrong twice
            # over: a pin carrying a STALE default stayed silent (exactly the case 13.6
            # exists for), and a pin carrying the DECIDED value got reported as a problem
            # even though it was the only thing making that checkout correct. The shipped
            # rule is that a decision-bearing value is not pinned here in EITHER
            # direction, so any presence is the finding; `agrees` only ranks it.
            example = _typed(name, example_values[key])
            out["latent"].append({
                **row, "example": example, "example_file": str(example_file),
                "agrees": example == decision.decided,
            })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", type=Path,
                        default=_REPO_ROOT / str(Settings.model_config.get("env_file") or ".env"),
                        help="the .env to audit (default: the one in the repo root — "
                             "resolved from __file__, NOT the cwd, because a report run "
                             "from elsewhere would otherwise print a clean bill of health "
                             "for a file it never read)")
    args = parser.parse_args()
    example_file = Path(str(args.env_file) + _EXAMPLE_SUFFIX)
    found = collect(os.environ, args.env_file, example_file)

    state = found["state"][0]
    print(f"decision-bearing settings declared: {len(DECISIONS)}")
    print(f"env file: {state['env_file']} ({state['env_state']})   "
          f"example: {state['example_file']} ({state['example_state']})")

    print("\n── effective value vs decided verdict ──")
    for row in found["drift"]:
        print(f"  DRIFT  {row['field']}: decided {row['decided']!r} "
              f"(story {row['story']}, {row['date']}) but effective {row['effective']!r} "
              f"from {row['source']} [code default {row['default']!r}]")
        print(f"         verdict: {row['citation']}")
    if not found["drift"]:
        print("  no drift — every decided value is the effective value")

    print("\n── env-sourced values (reported even when they match) ──")
    for row in found["env_sourced"]:
        match = "matches the decision" if row["effective"] == row["decided"] else "DIFFERS"
        print(f"  ENV    {row['field']} = {row['effective']!r} from {row['source']} ({match}); "
              f"code default {row['default']!r}")
    if not found["env_sourced"]:
        checked = state["env_state"] == "present"
        print("  none — every decided value comes from the code default" if checked else
              f"  NOT CHECKED — {state['env_file']} is {state['env_state']}, so an "
              "env-sourced value here would be invisible to this run")

    print("\n── latent pins in the example file (a fresh checkout would copy these) ──")
    for row in found["latent"]:
        verdict = "agrees with the verdict today, but is a second place to keep in step" \
            if row["agrees"] else "REVERTS the verdict"
        print(f"  LATENT {row['field']}: {row['example_file']} pins {row['example']!r} "
              f"({verdict}); decided {row['decided']!r}, code default {row['default']!r}")
    if not found["latent"]:
        checked = state["example_state"] == "present"
        print("  none — the example file pins no decision-bearing value at all" if checked else
              f"  NOT CHECKED — {state['example_file']} is {state['example_state']}")

    for row in found["stale"]:
        print(f"\n  STALE  DECISIONS['{row['field']}']: {row['why']} "
              f"(story {row['story']}, {row['date']}) — the table needs updating")

    print("\n── every declared setting, and where its value came from ──")
    for row in found["all"]:
        flag = "  " if row["effective"] == row["decided"] else "!!"
        print(f"  {flag} {row['field']} = {row['effective']!r}  "
              f"(decided {row['decided']!r} by story {row['story']}, {row['date']})  "
              f"source: {row['source']}")

    print("\nA non-empty result is a finding for the story that owns the feature, "
          "never a build failure. Exiting 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
