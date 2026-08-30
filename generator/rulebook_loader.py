"""Load the reason-code rulebook.

WHY THERE IS NO FALLBACK PARSER ANY MORE
-----------------------------------------
This module used to carry a hand-rolled `_mini_parse` for the case where PyYAML
was not installed. It looked for a top-level `reason_codes:` key. The rulebook
was restructured at v3 and now uses `codes:`, with `required_evidence` as a
mapping rather than a list.

The fallback was never updated. On a machine without PyYAML it therefore
returned `{"clocks": {}, "reason_codes": {}}` -- an empty rulebook, with no
error. Every downstream caller then saw zero required evidence for every code:
the generator would emit disputes with no artifacts, packet completeness would
be vacuously perfect, and the verifier would have nothing to check. The whole
pipeline would run cleanly and produce nonsense.

A missing dependency that degrades silently is worse than one that stops the
run. So it stops the run.
"""
import os

RULEBOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "rulebook", "reason_codes.yaml")


def load_rulebook(path=RULEBOOK_PATH):
    """Return the parsed rulebook. Raises rather than degrading."""
    try:
        import yaml
    except ImportError:
        raise SystemExit(
            "PyYAML is required to read the rulebook.\n"
            "  pip install pyyaml\n"
            "There is deliberately no fallback parser: an empty rulebook would "
            "let the pipeline run and produce meaningless results.")

    if not os.path.exists(path):
        raise SystemExit(f"Rulebook not found at {os.path.abspath(path)}")

    with open(path, encoding="utf-8") as f:
        book = yaml.safe_load(f)

    _validate(book, path)
    return book


def _validate(book, path):
    """Fail on a rulebook that parses but is not the shape we expect.

    Cheap, and it catches the class of error the old fallback produced: a
    structurally valid object with nothing useful in it.
    """
    if not isinstance(book, dict):
        raise SystemExit(f"Rulebook at {path} did not parse to a mapping.")

    if "codes" not in book:
        found = ", ".join(sorted(book)) or "nothing"
        raise SystemExit(
            f"Rulebook at {path} has no 'codes' key. Found: {found}.\n"
            "v1 used 'reason_codes'; v3 uses 'codes' with required_evidence "
            "as a {kind: api_field} mapping.")

    codes = book["codes"]
    if not codes:
        raise SystemExit(f"Rulebook at {path} defines no reason codes.")

    for code, entry in codes.items():
        req = entry.get("required_evidence")
        if not req:
            raise SystemExit(
                f"Reason code {code} has no required_evidence. A code with no "
                "evidence requirement makes packet completeness vacuous.")
        if not isinstance(req, dict):
            raise SystemExit(
                f"Reason code {code}: required_evidence should map each "
                f"evidence kind to a Razorpay contest API field, got "
                f"{type(req).__name__}.")

    return book