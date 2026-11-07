"""Guard reusable discovery assets against boilerplate and contradictory examples."""
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
        for step, title in enumerate(("发现选择点", "判断重要性与归属", "核对已有答案", "判断当前时机"), 1):
            self.assertIn(f"{step}. **{title}**", rules)
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
            self.assertEqual(c["format"], "semantic-choice-example.v1")
            self.assertNotIn("candidates", c)
            prefix, variant = c["case_id"].rsplit("-", 1)
            groups.setdefault(prefix, {})[variant] = c
            self.assertIn(variant, ("missing", "explicit", "future"))
            for candidate in c["choices_to_consider"]:
                self.assertTrue(candidate["topic"].strip())
                self.assertTrue(candidate["consequence"].strip())
                self.assertTrue(candidate["consequence"].strip())
                self.assertNotIn("不同选择会改变当前产品的访问、行为或交付范围", candidate["consequence"])
                options = candidate["alternatives"]
                self.assertIn(len(options), (2, 3))
                self.assertEqual(len({o["name"] for o in options}), len(options))
                self.assertEqual(len({o["consequence"] for o in options}), len(options))
                for option in options:
                    self.assertGreater(len(option["consequence"].strip()), 15)
                    self.assertNotIn("采用更受限的范围", option["consequence"])
                    self.assertNotIn("采用更开放的范围", option["consequence"])
        self.assertEqual(len(groups), 8)
        for variants in groups.values():
            self.assertEqual(set(variants), {"missing", "explicit", "future"})
            self.assertEqual(variants["explicit"]["choices_to_consider"], [])
            self.assertEqual(
                len(variants["missing"]["choices_to_consider"]),
                len(variants["future"]["choices_to_consider"]))
            for c in variants["future"]["choices_to_consider"]:
                self.assertEqual(c["timing"], "DEFER")

    def test_acceptance_instruction_explicitly_limits_self_verification(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        guidance = (REFERENCE / "scenario-probes.md").read_text(encoding="utf-8")
        self.assertIn("仅在确有需求时使用完整工具集", skill)
        self.assertIn("Codex 原生能力", skill)
        self.assertIn("不默认创建验收集合", skill)
        self.assertIn("独立认证", skill)
        self.assertIn("用户明确要求", skill)
        self.assertIn("不得标为通过", guidance)


if __name__ == "__main__":
    unittest.main()
