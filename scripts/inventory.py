#!/usr/bin/env python3
"""Read-only UUID inventory and internal consumer graph for this export subset."""

import argparse
from collections import Counter, defaultdict
import json
import re
import sys

from template_io import DIST, TemplateError, read_xml


def item_references(expression, owner):
    """Scan function item arguments, respecting quoted/bracketed key parameters.

    Not a general Zabbix expression parser. Unsupported/malformed item references
    fail rather than being silently omitted. Actual syntax is checked by Zabbix.
    """
    result = []
    for match in re.finditer(r"\b[A-Za-z_]\w*\(\s*/", expression):
        start = match.end()
        slash = expression.find("/", start)
        if slash < 0:
            raise TemplateError(f"Malformed item reference: {expression}")
        host = expression[start:slash] or owner
        if not host:
            raise TemplateError(f"Relative reference without template owner: {expression}")
        pos = slash + 1
        begin = pos
        brackets = braces = 0
        quoted = escaped = False
        while pos < len(expression):
            char = expression[pos]
            if escaped:
                escaped = False
            elif char == "\\" and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted:
                if char in ",)" and brackets == 0 and braces == 0:
                    break
                if char == "[":
                    brackets += 1
                elif char == "]":
                    brackets -= 1
                elif char == "{":
                    braces += 1
                elif char == "}":
                    braces -= 1
            pos += 1
        key = expression[begin:pos].strip()
        if not key or brackets or braces or quoted or pos == len(expression):
            raise TemplateError(f"Malformed item key reference: {expression}")
        result.append((host, key))
    return result


def analyze(root):
    entities = []
    elements = {}
    contexts = {}
    edges = set()
    errors, warnings = [], []

    def walk(element, owner="", lld="", parent="", path="/zabbix_export"):
        if element.tag == "template" and element.find("uuid") is not None:
            owner = element.findtext("template", "")
        if element.tag == "discovery_rule":
            lld = element.findtext("key", "")
        uuid = element.findtext("uuid", "")
        if uuid:
            if uuid in elements:
                errors.append(f"Duplicate UUID: {uuid}")
            if not re.fullmatch(r"[0-9a-f]{32}", uuid):
                errors.append(f"Invalid UUID: {uuid}")
            elements[uuid] = element
            entities.append({"uuid": uuid, "kind": element.tag, "template": owner,
                             "lld": lld, "key": element.findtext("key", ""),
                             "name": element.findtext("name", ""), "path": path})
            if parent:
                edges.add((parent, uuid, "contains"))
            parent = uuid
        contexts[element] = (owner, lld, parent, path)
        count = Counter()
        for child in element:
            count[child.tag] += 1
            walk(child, owner, lld, parent, f"{path}/{child.tag}[{count[child.tag]}]")

    walk(root)
    byid = {e["uuid"]: e for e in entities}
    bykey, templates = {}, {}
    group_names = {g.findtext("name") for g in root.findall("groups/group")}
    for e in entities:
        if e["kind"] == "template":
            if e["template"] in templates:
                errors.append(f"Duplicate template: {e['template']}")
            templates[e["template"]] = e["uuid"]
        if e["key"]:
            identity = (e["template"], e["key"])
            if identity in bykey:
                errors.append(f"Duplicate scoped key: {identity}")
            bykey[identity] = e["uuid"]

    def reference(host, key, consumer, kind):
        source = bykey.get((host, key))
        if source is None:
            errors.append(f"Missing {kind} reference: {host}/{key} -> {consumer}")
            return
        if byid[source]["kind"] not in {"item", "item_prototype"}:
            errors.append(f"{kind} target is not an item: {host}/{key}")
        source_lld = byid[source]["lld"]
        if source_lld and source_lld != byid[consumer]["lld"]:
            errors.append(f"Cross-LLD reference: {host}/{key} -> {consumer}")
        edges.add((source, consumer, kind))

    # Establish root graph/trigger owners before trigger-dependency resolution.
    for e in entities:
        node = elements[e["uuid"]]
        if not e["template"] and e["kind"] in {"trigger", "graph"}:
            hosts = {n.findtext("item/host") for n in node.findall("graph_items/graph_item")}
            for name in ("expression", "recovery_expression"):
                hosts.update(h for h, _ in item_references(node.findtext(name, ""), ""))
            hosts.discard(None)
            e["template"] = next(iter(hosts)) if len(hosts) == 1 else ""

    trigger_lookup = defaultdict(list)
    for e in entities:
        node = elements[e["uuid"]]
        if e["kind"] in {"trigger", "trigger_prototype"}:
            trigger_lookup[(e["template"], e["lld"], e["name"],
                            node.findtext("expression", ""), node.findtext("recovery_expression", ""))].append(e["uuid"])

    for e in entities:
        uuid, owner = e["uuid"], e["template"]
        node = elements[uuid]
        master = node.findtext("master_item/key")
        if node.findtext("type") == "DEPENDENT" and not master:
            errors.append(f"Dependent entity without master_item: {uuid}")
        if node.findtext("type") == "CALCULATED" and not node.findtext("params"):
            errors.append(f"Calculated entity without params: {uuid}")
        if master:
            reference(owner, master, uuid, "master")
        for field in ("params", "expression", "recovery_expression"):
            for host, key in item_references(node.findtext(field, ""), owner):
                reference(host, key, uuid, "formula" if field == "params" else field)
        for graph_item in node.findall("graph_items/graph_item"):
            reference(graph_item.findtext("item/host"), graph_item.findtext("item/key"), uuid, "graph")
        for link in node.findall("templates/template"):
            name = link.findtext("name")
            if name not in templates:
                errors.append(f"Unknown template link: {name} -> {uuid}")
            else:
                edges.add((templates[name], uuid, "template_link"))
        for group in node.findall("groups/group") + node.findall("group_links/group_link/group"):
            if group.findtext("name") not in group_names:
                errors.append(f"Unknown group: {group.findtext('name')} -> {uuid}")
        for dep in node.findall("dependencies/dependency"):
            identity = (owner, e["lld"], dep.findtext("name"), dep.findtext("expression"),
                        dep.findtext("recovery_expression", ""))
            candidates = trigger_lookup.get(identity, [])
            if len(candidates) != 1:
                errors.append(f"Unresolved/ambiguous trigger dependency: {identity} -> {uuid}")
            else:
                edges.add((candidates[0], uuid, "trigger_dependency"))

    # Cycles in calculation/master and trigger dependencies, not containment.
    adjacent = defaultdict(list)
    for source, consumer, kind in edges:
        if kind in {"master", "formula", "trigger_dependency"}:
            adjacent[source].append(consumer)
    visiting, done = set(), set()

    def visit(uuid):
        if uuid in visiting:
            errors.append(f"Dependency cycle at UUID {uuid}")
            return
        if uuid in done:
            return
        visiting.add(uuid)
        for consumer in adjacent[uuid]:
            visit(consumer)
        visiting.remove(uuid)
        done.add(uuid)

    for uuid in byid:
        visit(uuid)

    # Existing unresolved LLD macros are preserved and explicitly reported.
    macro_names = {}
    for d in root.findall("templates/template/discovery_rules/discovery_rule"):
        owner = contexts[d][0]
        macro_names[(owner, d.findtext("key"))] = {
            n.findtext("lld_macro") for n in d.findall("lld_macro_paths/lld_macro_path")}
    for node, (owner, lld, uuid, path) in contexts.items():
        if len(node) or not node.text:
            continue
        for macro in sorted(set(re.findall(r"\{#[A-Za-z0-9_.]+\}", node.text))):
            if macro not in macro_names.get((owner, lld), set()):
                warnings.append({"uuid": uuid, "path": path, "macro": macro,
                                 "message": "LLD macro not defined in this discovery scope"})
    return {"schema_scope": "project Zabbix 6.0 subset; not a complete expression/import validator",
            "counts": dict(sorted(Counter(e["kind"] for e in entities).items())),
            "entities": entities,
            "edges": [{"source": s, "consumer": c, "kind": k} for s, c, k in sorted(edges)],
            "errors": sorted(set(errors)), "warnings": warnings,
            "external_consumers": "Not available in this template export: live overrides, dashboards, actions, API clients"}


def markdown(report):
    def esc(text):
        return str(text).replace("|", "&#124;").replace("\n", " ")

    byid = {e["uuid"]: e for e in report["entities"]}
    outgoing = defaultdict(list)
    for edge in report["edges"]:
        if edge["kind"] != "contains":
            target = byid[edge["consumer"]]
            label = target["key"] or target["name"]
            outgoing[edge["source"]].append(f"{edge['kind']} -> {label} ({target['uuid']})")
    rows = ["# Связи и потребители шаблонов", "",
            "Генерируется `python scripts/inventory.py --format markdown`. Не редактировать вручную.", "",
            f"UUID-сущностей: {len(byid)}; рёбер (включая contains): {len(report['edges'])}; "
            f"ошибок: {len(report['errors'])}; предупреждений LLD scope: {len(report['warnings'])}.", "",
            "Направление: источник -> потребитель. Полный JSON включает contains и UUID всех концов.",
            "Внешние потребители не проверены. Макросы уровня host/global не разрешаются офлайн.", ""]
    last_owner = None
    for e in report["entities"]:
        owner = e["template"] or "export"
        if owner != last_owner:
            rows += [f"## {owner}", "", "| Объект / UUID | LLD | Потребители |", "| --- | --- | --- |"]
            last_owner = owner
        rows.append("| " + " | ".join(map(esc, [f"{e['kind']}: {e['key'] or e['name']} / {e['uuid']}",
                                                  e["lld"] or "—", "; ".join(outgoing[e["uuid"]]) or "—"])) + " |")
    rows += ["", "## Ошибки", ""] + (report["errors"] or ["Нет ошибок внутренних ссылок."])
    rows += ["", "## Существующие предупреждения LLD scope", ""]
    rows.extend(f"- `{w['uuid']}`: `{w['macro']}` в `{w['path']}`." for w in report["warnings"])
    return "\n".join(rows) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", default=DIST)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()
    try:
        report = analyze(read_xml(args.xml))
        print(markdown(report) if args.format == "markdown" else json.dumps(report, ensure_ascii=False, indent=2), end="\n")
        return 1 if report["errors"] else 0
    except (TemplateError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
