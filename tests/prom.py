"""Match Prometheus selectors against synthetic rows for RAVPN tests."""

import re

SELECTOR = re.compile(r"^(?P<name>[^{]+?)?(?:\{(?P<body>.*)\})?\s*$")
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*(=~|!~|!=|=)\s*"((?:\\.|[^"\\])*)"')
USER_MACRO = re.compile(r"\{\$[A-Za-z0-9._]+\}")


def _unescape(value):
    return value.replace(r"\\", "\\").replace(r"\"", '"').replace(r"\n", "\n")


def _compile(pattern):
    return re.compile(pattern)


def _match_op(op, expected, actual):
    if "{#" in expected:
        return True
    if op == "=":
        return actual == expected
    if op == "!=":
        return actual != expected
    regex = _compile(expected)
    found = regex.search(actual or "") is not None
    return found if op == "=~" else not found


def parse_selector(raw):
    match = SELECTOR.match(raw.strip())
    if not match:
        raise ValueError(f"Unsupported Prometheus selector: {raw}")
    name = (match.group("name") or "").strip()
    body = match.group("body") or ""
    matchers = []
    if body:
        consumed = 0
        for label in LABEL.finditer(body):
            if body[consumed:label.start()].strip() not in {"", ","}:
                raise ValueError(f"Unsupported Prometheus selector: {raw}")
            matchers.append((label.group(1), label.group(2), _unescape(label.group(3))))
            consumed = label.end()
        if body[consumed:].strip() not in {"", ","}:
            raise ValueError(f"Unsupported Prometheus selector: {raw}")
    name_matcher = None
    rest = []
    if name:
        name_matcher = ("__name__", "=", name)
    for key, op, value in matchers:
        if key == "__name__":
            name_matcher = (key, op, value)
        else:
            rest.append((key, op, value))
    if name_matcher is None:
        raise ValueError(f"Selector has no metric name: {raw}")
    return name_matcher, rest


def substitute_macros(selector, macros):
    def replace(match):
        return macros.get(match.group(0), match.group(0))

    return USER_MACRO.sub(replace, selector)


def series_matches(series, selector, macros=None):
    raw = substitute_macros(selector, macros or {})
    name_matcher, labels = parse_selector(raw)
    _, op, expected = name_matcher
    if not _match_op(op, expected, series["name"]):
        return False
    for key, label_op, value in labels:
        if not _match_op(label_op, value, series["labels"].get(key, "")):
            return False
    return True


def select(series, selector, macros=None):
    return [item for item in series if series_matches(item, selector, macros)]
