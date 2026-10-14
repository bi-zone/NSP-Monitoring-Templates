"""Lossless codec for the project's supported subset of Zabbix 6.0 export."""

from pathlib import Path
import xml.etree.ElementTree as ET

import yaml


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist/zabbix-6.0/CSP_all_templates.xml"


class TemplateError(ValueError):
    pass


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise TemplateError(f"YAML key must be a string at line {key_node.start_mark.line + 1}")
            if key in result:
                raise TemplateError(f"Duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


class LiteralDumper(yaml.SafeDumper):
    pass


def represent_string(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value,
                                   style="|" if "\n" in value else None)


LiteralDumper.add_representer(str, represent_string)


def load_yaml(path):
    try:
        return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=StrictLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise TemplateError(f"{path}: {exc}") from exc


def dump_yaml(data):
    return yaml.dump(data, Dumper=LiteralDumper, allow_unicode=True,
                     sort_keys=False, width=110)


# A scalar is None, an object is its schema name, a list is (element tag, schema).
def fields(scalars="", **nested):
    return dict.fromkeys(scalars.split()) | nested


SCHEMAS = {
    "export": fields("version date", groups=("group", "group"),
                     templates=("template", "template"), triggers=("trigger", "trigger"),
                     graphs=("graph", "graph")),
    "group": fields("uuid name"),
    "group_ref": fields("name"),
    "template_ref": fields("name"),
    "template": fields("uuid template name description", groups=("group", "group_ref"),
                       items=("item", "item"), discovery_rules=("discovery_rule", "lld"),
                       macros=("macro", "macro"), templates=("template", "template_ref")),
    "item": fields("uuid name type key delay history trends value_type units description "
                   "params inventory_link timeout url ssl_cert_file ssl_key_file status",
                   preprocessing=("step", "preprocess"), master_item="master",
                   triggers=("trigger", "trigger"), tags=("tag", "tag"),
                   query_fields=("query_field", "query")),
    "prototype": fields("uuid name type key delay history trends value_type units description params status discover",
                        preprocessing=("step", "preprocess"), master_item="master",
                        trigger_prototypes=("trigger_prototype", "trigger_prototype"), tags=("tag", "tag")),
    "master": fields("key"),
    "preprocess": fields("type error_handler error_handler_params", parameters=("parameter", None)),
    "query": fields("name value"),
    "trigger": fields("uuid expression recovery_mode recovery_expression name priority description "
                      "manual_close status opdata", dependencies=("dependency", "dependency"), tags=("tag", "tag")),
    "dependency": fields("name expression recovery_expression"),
    "lld": fields("uuid name type key delay description lifetime status",
                  master_item="master", preprocessing=("step", "preprocess"), filter="filter",
                  lld_macro_paths=("lld_macro_path", "lld_macro"),
                  item_prototypes=("item_prototype", "prototype"),
                  trigger_prototypes=("trigger_prototype", "trigger_prototype"),
                  graph_prototypes=("graph_prototype", "graph_prototype"),
                  host_prototypes=("host_prototype", "host"), overrides=("override", "override")),
    "host": fields("uuid host name", group_links=("group_link", "group_link"),
                   templates=("template", "template_ref"), macros=("macro", "macro")),
    "group_link": fields(group="group_ref"),
    "macro": fields("macro value description type"),
    "lld_macro": fields("lld_macro path"),
    "filter": fields("evaltype formula", conditions=("condition", "condition")),
    "condition": fields("macro value operator formulaid"),
    "graph": fields("uuid name width height yaxismin yaxismax show_work_period show_triggers type show_3d",
                    graph_items=("graph_item", "graph_item")),
    "graph_item": fields("sortorder color calc_fnc yaxisside drawtype type", item="graph_ref"),
    "graph_ref": fields("host key"),
    "override": fields("name step stop", filter="filter", operations=("operation", "operation")),
    "operation": fields("operationobject operator value status discover severity", tags=("tag", "tag")),
    "tag": fields("tag value"),
}
SCHEMAS["trigger_prototype"] = SCHEMAS["trigger"] | fields("discover")
SCHEMAS["graph_prototype"] = SCHEMAS["graph"] | fields("discover")

REQUIRED = {
    "export": "version groups templates", "group": "uuid name", "group_ref": "name",
    "template_ref": "name", "template": "uuid template groups", "item": "uuid name key",
    "prototype": "uuid name key", "master": "key", "preprocess": "type parameters",
    "query": "name value", "trigger": "uuid expression name", "dependency": "name expression",
    "lld": "uuid name key", "host": "uuid host group_links", "group_link": "group",
    "macro": "macro value", "lld_macro": "lld_macro path", "condition": "macro value formulaid",
    "graph": "uuid name graph_items", "graph_item": "color item", "graph_ref": "host key",
    "override": "name step operations", "operation": "operationobject", "tag": "tag value",
}
REQUIRED["trigger_prototype"] = REQUIRED["trigger"]
REQUIRED["graph_prototype"] = REQUIRED["graph"]


def validate_data(data, schema="export", path="zabbix_export", partial=False):
    if schema is None:
        if not isinstance(data, str):
            raise TemplateError(f"{path}: expected quoted string, got {type(data).__name__}")
        return
    if not isinstance(data, dict):
        raise TemplateError(f"{path}: expected mapping")
    unknown = set(data) - set(SCHEMAS[schema])
    if unknown:
        raise TemplateError(f"{path}: unsupported fields {sorted(unknown)}")
    if not partial:
        missing = set(REQUIRED.get(schema, "").split()) - set(data)
        if missing:
            raise TemplateError(f"{path}: missing fields {sorted(missing)}")
    for key, value in data.items():
        spec = SCHEMAS[schema][key]
        child_path = f"{path}/{key}"
        if isinstance(spec, tuple):
            if not isinstance(value, list):
                raise TemplateError(f"{child_path}: expected list, including for one element")
            for index, entry in enumerate(value):
                validate_data(entry, spec[1], f"{child_path}[{index}]")
        else:
            validate_data(value, spec, child_path)
    if schema == "export" and "version" in data and data["version"] != "6.0":
        raise TemplateError("Only export version '6.0' is implemented")


def xml_to_data(element, schema="export"):
    if schema is None:
        if len(element) or element.attrib:
            raise TemplateError(f"{element.tag}: expected XML leaf")
        return element.text or ""
    if element.attrib or (element.text or "").strip():
        raise TemplateError(f"{element.tag}: attributes/mixed content not supported")
    data = {}
    for child in element:
        if child.tag not in SCHEMAS[schema] or child.tag in data:
            raise TemplateError(f"{element.tag}: unknown/duplicate XML field {child.tag}")
        if (child.tail or "").strip():
            raise TemplateError(f"{child.tag}: mixed content not supported")
        spec = SCHEMAS[schema][child.tag]
        if isinstance(spec, tuple):
            if child.attrib or (child.text or "").strip():
                raise TemplateError(f"{child.tag}: invalid list container")
            if any(c.tag != spec[0] for c in child):
                raise TemplateError(f"{child.tag}: expected only {spec[0]} elements")
            data[child.tag] = [xml_to_data(c, spec[1]) for c in child]
        else:
            data[child.tag] = xml_to_data(child, spec)
    return data


def data_to_xml(data, tag="zabbix_export", schema="export"):
    element = ET.Element(tag)
    if schema is None:
        element.text = data
        return element
    for key, value in data.items():
        spec = SCHEMAS[schema][key]
        if isinstance(spec, tuple):
            container = ET.SubElement(element, key)
            for entry in value:
                container.append(data_to_xml(entry, spec[0], spec[1]))
        else:
            element.append(data_to_xml(value, key, spec))
    return element


def read_xml(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise TemplateError(f"{path}: {exc}") from exc
    if root.tag != "zabbix_export":
        raise TemplateError("Expected zabbix_export root")
    data = xml_to_data(root)
    validate_data(data)
    return root


def serialize(data):
    validate_data(data)
    root = data_to_xml(data)
    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
