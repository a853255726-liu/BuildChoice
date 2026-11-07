"""Static regression checks for P0 assumption-first discovery examples.

These guard fixture and guidance consistency; they do not measure LLM recall,
question quality, or real Codex behavior.
"""
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/buildchoice/skills/decision-discovery"


class CandidateDiscoveryExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [
            json.loads(line)
            for line in (SKILL / "references/examples.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        cls.by_id = {row["case_id"]: row for row in cls.rows}

    def test_examples_are_unique_and_have_concrete_choice_consequences(self):
        self.assertEqual(len(self.rows), len(self.by_id))
        for row in self.rows:
            with self.subTest(case=row["case_id"]):
                self.assertEqual(row["format"], "semantic-choice-example.v1")
                self.assertTrue(row["task"].strip())
                self.assertIn("choices_to_consider", row)
                for choice in row["choices_to_consider"]:
                    self.assertIn(choice["timing"], {"ASK_NOW", "DEFER", "INSPECT", "PROCEED"})
                    self.assertEqual(len(choice["alternatives"]), 2)
                    self.assertNotEqual(
                        choice["alternatives"][0]["consequence"],
                        choice["alternatives"][1]["consequence"],
                    )
                    self.assertTrue(choice["user_question"].strip())
                    self.assertTrue(choice["consequence"].strip())

    def test_open_scope_is_timed_by_current_dependency(self):
        immediate = self.by_id["p0-open-scope-now"]
        deferred = self.by_id["p0-open-scope-defer"]
        self.assertEqual(immediate["choices_to_consider"][0]["timing"], "ASK_NOW")
        self.assertEqual(deferred["choices_to_consider"][0]["timing"], "DEFER")
        self.assertEqual(
            immediate["choices_to_consider"][0]["alternatives"],
            deferred["choices_to_consider"][0]["alternatives"],
        )

    def test_no_spurious_choice_for_resolved_delegated_or_undefined_goal(self):
        for case_id in (
            "p0-open-scope-user-decided",
            "p0-open-scope-project-decided",
            "p0-open-delegated",
            "p0-missing-purpose",
            "p0-ui-explanations-not-choice",
            "p0-bounded-change",
        ):
            with self.subTest(case=case_id):
                self.assertEqual(self.by_id[case_id]["choices_to_consider"], [])
        self.assertFalse(self.by_id["p0-missing-purpose"]["has_answer"])

    def test_skill_uses_existing_candidate_entry_not_a_new_workflow(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        candidate = (SKILL / "references/candidate-rules.md").read_text(encoding="utf-8")
        probes = (SKILL / "references/scenario-probes.md").read_text(encoding="utf-8")
        self.assertIn("最小拟议方案", skill)
        self.assertIn("references/candidate-rules.md", skill)
        self.assertIn("## 从当前方案寻找关键假设（P0）", candidate)
        self.assertIn("ASK_NOW", candidate)
        self.assertIn("INSPECT", candidate)
        self.assertIn("DEFER", candidate)
        self.assertIn("PROCEED", candidate)
        self.assertIn("candidate-rules.md", probes)


if __name__ == "__main__":
    unittest.main()
