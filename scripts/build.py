#!/usr/bin/env python3
"""Build the committed XML, or check it without writing (--check)."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

from template_io import ROOT, TemplateError, load_yaml, serialize, validate_data


def inside(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise TemplateError("Profile paths must be relative strings")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise TemplateError(f"Profile path escapes project: {relative}")
    return resolved


def assemble(root=ROOT, profile="zabbix-6.0"):
    if profile != "zabbix-6.0":
        raise TemplateError(f"Unsupported profile: {profile}")
    config = load_yaml(root / "profiles" / f"{profile}.yaml")
    expected = {"engine", "export_version", "status", "tested_engine_patch",
                "tested_csp_version", "output", "sources"}
    if not isinstance(config, dict) or set(config) != expected:
        raise TemplateError("Unexpected/missing profile fields")
    if (config["engine"], config["export_version"], config["status"]) != ("zabbix", "6.0", "active"):
        raise TemplateError("Only active Zabbix 6.0 profile is supported")
    sources = config["sources"]
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) for s in sources):
        raise TemplateError("Profile sources must be a non-empty list of paths")
    if len(set(sources)) != len(sources):
        raise TemplateError("Duplicate source path")
    merged = {}
    for source in sources:
        document = load_yaml(inside(root, source))
        if not isinstance(document, dict) or set(document) != {"zabbix_export"}:
            raise TemplateError(f"{source}: expected only zabbix_export")
        fragment = document["zabbix_export"]
        validate_data(fragment, partial=True)
        for key, value in fragment.items():
            if key in {"version", "date"}:
                if key in merged:
                    raise TemplateError(f"Duplicate export metadata: {key}")
                merged[key] = value
            else:
                merged.setdefault(key, []).extend(value)
    # Export section ordering is stable, independent of fragment root sections.
    merged = {key: merged[key] for key in ("version", "date", "groups", "templates", "triggers", "graphs")
              if key in merged}
    validate_data(merged)
    if len(merged["templates"]) != 3 or not merged["groups"]:
        raise TemplateError("This profile requires three templates and a non-empty group list")
    output = inside(root, config["output"])
    if not output.is_relative_to((root / "dist").resolve()):
        raise TemplateError("Profile output must be inside dist/")
    return merged, output


def render(root=ROOT, profile="zabbix-6.0"):
    from inventory import analyze
    import xml.etree.ElementTree as ET

    data, output = assemble(root, profile)
    content = serialize(data)
    report = analyze(ET.fromstring(content))
    if report["errors"]:
        raise TemplateError("Reference validation failed:\n" + "\n".join(report["errors"]))
    return content, output, report


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    filename = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            filename = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(filename, 0o644)
        os.replace(filename, path)
    finally:
        if filename and os.path.exists(filename):
            os.unlink(filename)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="zabbix-6.0")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        content, output, report = render(profile=args.profile)
        if args.check:
            if not output.exists() or output.read_bytes() != content:
                raise TemplateError(f"STALE/MISSING: {output}; run scripts/build.py")
            print(f"PASS: dist matches source ({len(report['entities'])} UUIDs)")
        else:
            atomic_write(output, content)
            print(f"Built {output} ({len(report['entities'])} UUIDs)")
        print(f"Known macro-scope warnings: {len(report['warnings'])}; see scripts/inventory.py")
        return 0
    except (TemplateError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
