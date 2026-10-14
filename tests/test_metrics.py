"""Template structure and regression checks without environment captures."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build
from inventory import analyze


class TemplateTests(unittest.TestCase):
    def test_yaml_builds_and_our_internal_references_resolve(self):
        content, output, report = build.render()
        self.assertTrue(output.as_posix().endswith("CSP_all_templates.xml"))
        self.assertEqual([], report["errors"])
        self.assertEqual(3, len({e["template"] for e in report["entities"] if e["kind"] == "template"}))
        self.assertEqual(content, build.render()[0])
        live = analyze(__import__("xml.etree.ElementTree", fromlist=["ET"]).fromstring(content))
        self.assertEqual([], live["errors"])

    def test_swap_percentages_and_trigger_have_consistent_semantics(self):
        data, _ = build.assemble()
        csp = next(template for template in data["templates"]
                   if template["template"] == "BI.ZONE Secure SD-WAN. CSP-controller template")
        items = {item["key"]: item for item in csp["items"]}
        self.assertEqual(
            '(last(//csp.swap.free)+count(//csp.swap.total,#1,"eq",0))/(last(//csp.swap.total)+count(//csp.swap.total,#1,"eq",0))*100',
            items["csp.swap.pfree"]["params"],
        )
        self.assertEqual(
            '(last(//csp.swap.total)-last(//csp.swap.free))/(last(//csp.swap.total)+count(//csp.swap.total,#1,"eq",0))*100',
            items["csp.swap.pused"]["params"],
        )
        trigger = next(item for item in data["triggers"]
                       if item["name"] == "HostSwapIsFillingUp")
        self.assertEqual(
            "min(/BI.ZONE Secure SD-WAN. CSP-controller template/csp.swap.pused,5m)>80 and last(/BI.ZONE Secure SD-WAN. CSP-controller template/csp.swap.total)>0",
            trigger["expression"],
        )

    def test_unused_tcp_connections_discovery_is_removed(self):
        data, _ = build.assemble()
        cyberedge = next(template for template in data["templates"]
                         if template["template"] == "BI.ZONE Secure SD-WAN. CyberEdge")
        discovery_keys = {rule["key"] for rule in cyberedge["discovery_rules"]}
        self.assertNotIn("tcp.conn.discov", discovery_keys)
        self.assertNotIn("650caf66abe94d56a11329e8c7875fd9", repr(data))
        self.assertNotIn("0d7572d989524538907b4d2729602905", repr(data))

    def test_unused_multicast_prototypes_are_removed(self):
        data, _ = build.assemble()
        rendered = repr(data)
        self.assertNotIn("net.mltcst[{#BZMON_INTERFACE_NAME}]", rendered)
        self.assertNotIn("phys.net.mltcst[{#PHYS_IFNAME}]", rendered)
        self.assertNotIn("7ceb498f6f4b4fe18c39ccb84fe0c34d", rendered)
        self.assertNotIn("4cf1a32eb8ef4c8a9c08a83f1233abac", rendered)

    def test_invalid_unused_disk_prototypes_are_removed(self):
        data, _ = build.assemble()
        rendered = repr(data)
        self.assertNotIn('vfs.dev.queue_size["{#DEVNAME}"]', rendered)
        self.assertNotIn('vfs.dev.util["{#DEVNAME}"]', rendered)
        self.assertNotIn("c74a7e879ebc449cb25cd1219dae687e", rendered)
        self.assertNotIn("0a7b9a0f098345989a0a3b73beca9f5c", rendered)

    def test_unused_cpe_filesystem_prototypes_are_removed(self):
        data, _ = build.assemble()
        rendered = repr(data)
        removed = {
            "cpe.abs.free.fs[{#MOUNT_POINT}]": "8f3671a6df2440dbb4f0d293db7d0a4b",
            "cpe.abs.rsrvd.fs[{#MOUNT_POINT}]": "5d3039bd899a4c8a82a18c781f06de29",
            "cpe.abs.used.fs[{#MOUNT_POINT}]": "295c38dd158042e5a47f0918b41e670b",
            "cpe.rsrvd.fs[{#MOUNT_POINT}]": "03ce289d38e34d37915b58a85fe6f33c",
        }
        for key, uuid in removed.items():
            self.assertNotIn(key, rendered)
            self.assertNotIn(uuid, rendered)
        self.assertIn("cpe.free.fs[{#MOUNT_POINT}]", rendered)
        self.assertIn("cpe.used.fs[{#MOUNT_POINT}]", rendered)
