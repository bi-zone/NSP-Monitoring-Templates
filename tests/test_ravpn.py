"""Execute the actual RAVPN JavaScript with selected Prometheus rows (Node.js)."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build import assemble
from prom import select


def preprocess(entity, series, vpc=None):
    steps = entity["preprocessing"]
    selector = steps[0]["parameters"][0]
    if vpc is not None:
        selector = selector.replace("{#VPC_ID}", vpc)
    rows = select(series, selector)
    program = """
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = new Function('value', input.code)(JSON.stringify(input.rows));
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "-e", program],
        input=json.dumps({"code": steps[1]["parameters"][0], "rows": rows}),
        text=True, capture_output=True, check=True, timeout=10,
    )
    return json.loads(result.stdout)


class RavpnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise RuntimeError("Node.js is required to test RAVPN preprocessing")
        cls.templates = assemble()[0]["templates"]
        template = next(t for t in cls.templates
                        if any(i["key"] == "get.ravpn.metrics" for i in t["items"]))
        cls.template = template
        cls.items = [i for i in template["items"]
                     if i.get("master_item", {}).get("key") == "get.ravpn.metrics"]
        cls.discovery = next(r for r in template["discovery_rules"]
                             if r["key"] == "csp.ravpn.vpc.discov")
        cls.prototypes = cls.discovery["item_prototypes"]
        # Invented values and identifiers; no captured environment data.
        cls.expected = {
            "connections": {"online": 7, "offline": 2, "unknown": 0, "deleted": 3},
            "peers": {"online": 5, "offline": 4, "unknown": 1, "deleted": 0},
            "users": {"online": 0, "offline": 6, "inactive": 2},
            "devices": {"online": 8, "offline": 0, "inactive": 3},
        }
        cls.sample = [
            {"name": "ravpn_" + family, "value": str(value),
             "labels": {"vpc_id": "vpc-example", "status": status}}
            for family, statuses in cls.expected.items()
            for status, value in statuses.items()
        ]

    def test_cluster_metrics_have_one_owner_on_seed_host(self):
        owners = [t["template"] for t in self.templates
                  if any(i["key"] == "get.ravpn.metrics" for i in t["items"])]
        self.assertEqual(["BI.ZONE Secure SD-WAN. Discovery template"], owners)
        self.assertEqual("BI.ZONE Secure SD-WAN. Discovery template",
                         self.template["template"])
        csp = next(t for t in self.templates
                   if t["template"] == "BI.ZONE Secure SD-WAN. CSP-controller template")
        self.assertFalse(any("ravpn" in i["key"] for i in csp["items"]))
        self.assertFalse(any("ravpn" in r["key"] for r in csp["discovery_rules"]))

    def test_synthetic_values_including_explicit_zero(self):
        expected = self.expected
        self.assertEqual(14, len(self.items))
        self.assertEqual(14, len(self.prototypes))
        for item in self.items + self.prototypes:
            family, args = item["key"].removeprefix("csp.ravpn.").split("[")
            status = args.rstrip("]").split(",")[-1]
            with self.subTest(key=item["key"]):
                self.assertEqual(expected[family][status], preprocess(
                    item, self.sample, "vpc-example"))

    def test_multiple_vpcs_devices_and_peers_are_summed_independently(self):
        rows = []
        for metric, values in (("connections", (2, 3, 7)), ("peers", (4, 9, 11))):
            for (vpc, device), value in zip((("vpc-a", "cpe-a"),
                                           ("vpc-a", "cpe-b"),
                                           ("vpc-b", "cpe-a")), values):
                rows.append({"name": "ravpn_" + metric, "value": str(value),
                             "labels": {"vpc_id": vpc, "device_id": device,
                                        "status": "online"}})
        for metric, total, first, second in (("connections", 12, 5, 7),
                                             ("peers", 24, 13, 11)):
            item = next(i for i in self.items if i["key"] == f"csp.ravpn.{metric}[online]")
            proto = next(i for i in self.prototypes
                         if i["key"] == f"csp.ravpn.{metric}[{{#VPC_ID}},online]")
            self.assertEqual(total, preprocess(item, rows))
            self.assertEqual(first, preprocess(proto, rows, "vpc-a"))
            self.assertEqual(second, preprocess(proto, rows, "vpc-b"))

    def test_missing_series_is_not_a_zero_measurement(self):
        # Empty string deliberately fails numeric conversion in Zabbix.
        for item in self.items + self.prototypes:
            with self.subTest(key=item["key"]):
                self.assertEqual("", preprocess(item, [], "missing-vpc"))

    def test_discovery_deduplicates_and_does_not_require_online_users(self):
        rows = copy.deepcopy(self.sample)
        rows = [r for r in rows if r["name"] != "ravpn_users"]
        rows.extend([
            {"name": "ravpn_users", "value": "3",
             "labels": {"vpc_id": "offline-only", "status": "offline"}},
            {"name": "ravpn_devices", "value": "0",
             "labels": {"vpc_id": "inactive-only", "status": "inactive"}},
            {"name": "ravpn_service_requests_count", "value": "1",
             "labels": {"vpc_id": "histogram-only"}},
            {"name": "ravpn_users", "value": "1", "labels": {}},
        ])
        discovered = json.loads(preprocess(self.discovery, rows))
        self.assertEqual(["vpc-example", "offline-only", "inactive-only"],
                         [r["labels"]["vpc_id"] for r in discovered])
        self.assertEqual([], json.loads(preprocess(self.discovery, [])))
