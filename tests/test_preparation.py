import copy
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'examples'))
from common import encode_sample, load_data


class FakeTokenizer:
    """Exercises label boundaries without downloading a tokenizer."""
    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        prompt = [10, 11, 12]
        return prompt if add_generation_prompt else prompt + [20, 21, 99]


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.rows = load_data(ROOT / 'data/public/toy.jsonl')

    def check_rows(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'samples.jsonl'
            file.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            return load_data(file)

    def test_source_family_cannot_cross_split(self):
        rows = copy.deepcopy(self.rows)
        rows[1]['source_group'] = rows[0]['source_group']
        with self.assertRaisesRegex(ValueError, 'group crosses'):
            self.check_rows(rows)

    def test_identical_answer_cannot_cross_split(self):
        rows = copy.deepcopy(self.rows)
        rows[1]['target'] = rows[0]['target']
        with self.assertRaisesRegex(ValueError, 'target crosses'):
            self.check_rows(rows)

    def test_unreviewed_sample_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[0]['review_status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'not approved'):
            self.check_rows(rows)

    def test_missing_rule_input_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[0]['inputs']['rules'] = ''
        with self.assertRaisesRegex(ValueError, 'missing input'):
            self.check_rows(rows)

    def test_prompt_mask_preserves_answer_and_eos(self):
        result = encode_sample(FakeTokenizer(), self.rows[0], 6)
        self.assertEqual(result['labels'], [-100, -100, -100, 20, 21, 99])

    def test_oversized_answer_is_not_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, 'no silent truncation'):
            encode_sample(FakeTokenizer(), self.rows[0], 5)

    def test_chat_template_mismatch_is_rejected(self):
        class WrongTemplate(FakeTokenizer):
            def apply_chat_template(self, messages, tokenize, add_generation_prompt):
                return [1, 2] if add_generation_prompt else [9, 20]
        with self.assertRaisesRegex(ValueError, 'prefix mismatch'):
            encode_sample(WrongTemplate(), self.rows[0], 100)

    def test_handwritten_toy_targets_execute(self):
        # These are bundled, reviewed teaching fixtures, never model-generated candidates.
        suite = unittest.TestSuite()
        for row in self.rows:
            module = types.ModuleType(row['id'])
            exec(compile(row['target'], row['id'], 'exec'), module.__dict__)
            suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        self.assertEqual(result.testsRun, 3)
        self.assertTrue(result.wasSuccessful())


if __name__ == '__main__':
    unittest.main()
