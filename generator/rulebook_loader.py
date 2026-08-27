"""Load the reason-code rulebook. Uses PyYAML if present, else a tiny fallback."""
import os

RULEBOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "rulebook", "reason_codes.yaml")


def load_rulebook(path=RULEBOOK_PATH):
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        return _mini_parse(path)


def _mini_parse(path):
    """Minimal YAML reader for this file's specific shape. Prefer PyYAML."""
    import re
    data = {"clocks": {}, "reason_codes": {}}
    section = None
    code = None
    with open(path) as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            s = line.strip()
            if indent == 0:
                section = s.rstrip(":")
                continue
            if section == "clocks" and indent == 2:
                k, v = s.split(":", 1)
                data["clocks"][k.strip()] = int(v.strip())
            elif section == "reason_codes" and indent == 2:
                code = s.rstrip(":").strip().strip('"')
                data["reason_codes"][code] = {}
            elif section == "reason_codes" and indent == 4 and code:
                k, v = s.split(":", 1)
                k, v = k.strip(), v.strip()
                if k == "evidence":
                    items = re.findall(r"[\w]+", v)
                    data["reason_codes"][code][k] = items
                elif k == "clock_days":
                    data["reason_codes"][code][k] = int(v)
                else:
                    data["reason_codes"][code][k] = v
    return data
