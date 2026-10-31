"""Guard reusable discovery assets against boilerplate and contradictory examples.

These are asset/contract checks, not evidence that a coding Agent discovered
all material decisions in real-world user requests.
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/buildchoice/skills/decision-discovery"
REFERENCE = SKILL / "references"


class DiscoveryAssetTests(unittest.TestCase):
    def test_scenario_probes_are_locally_available_and_optional(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        guidance = (REFERENCE / "scenario-probes.md").read_text(encoding="utf-8")
        rules = (REFERENCE / "candidate-rules.md").read_text(encoding="utf-8")
        self.assertIn("references/scenario-probes.md", skill)
        self.assertIn("最多两类", skill)
        self.assertIn("四道门槛", rules)
        self.assertIn("不是独立分类器", guidance)
        self.assertIn("每种场景只扫描", guidance)
        self.assertIn("一个场景没有候选是正常结果", guidance)
        self.assertIn("没有候选", guidance)
        self.assertIn("不允许为了满足维度或场景的数量创造问题", guidance)

    def test_examples_have_noncontradictory_concrete_tradeoffs(self):
        lines = (REFERENCE / "examples.jsonl").read_text(encoding="utf-8").splitlines()
        cases = [json.loads(x) for x in lines if x.strip()]
        self.assertEqual(len(cases), 24)
        self.assertEqual(len(set(c["case_id"] for c in cases)), len(cases))
        groups = {}
        for c in cases:
            prefix, variant = c["case_id"].rsplit("-", 1)
            groups.setdefault(prefix, {})[variant] = c
            self.assertIn(variant, ("missing", "explicit", "future"))
            for candidate in c["expected_candidates"]:
                self.assertTrue(candidate["field"].strip())
                self.assertTrue(candidate["impact"].strip())
                self.assertTrue(candidate["why_user_choice"].strip())
                self.assertNotIn("不同选择会改变当前产品的访问、行为或交付范围", candidate["impact"])
                options = candidate["options"]
                self.assertIn(len(options), (2, 3))
                self.assertEqual(len({o["id"] for o in options}), len(options))
                self.assertEqual(len({o["tradeoff"] for o in options}), len(options))
                for option in options:
                    self.assertGreater(len(option["tradeoff"].strip()), 15)
                    self.assertNotIn("采用更受限的范围", option["tradeoff"])
                    self.assertNotIn("采用更开放的范围", option["tradeoff"])
        self.assertEqual(len(groups), 8)
        for variants in groups.values():
            self.assertEqual(set(variants), {"missing", "explicit", "future"})
            self.assertEqual(variants["explicit"]["expected_candidates"], [])
            self.assertEqual(
                len(variants["missing"]["expected_candidates"]),
                len(variants["future"]["expected_candidates"]))
            for c in variants["future"]["expected_candidates"]:
                self.assertEqual(c["current_dependency"], "no")

    def test_acceptance_instruction_explicitly_limits_self_verification(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        guidance = (REFERENCE / "scenario-probes.md").read_text(encoding="utf-8")
        self.assertIn("至少一个会违反条件的具体反例", skill)
        self.assertIn("Agent 编写测试", skill)
        self.assertIn("current_pass=true", skill)
        self.assertIn("不得标为通过", guidance)


if __name__ == "__main__":
    unittest.main()
