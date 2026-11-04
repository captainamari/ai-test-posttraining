"""Regression tests for the benchmark tools. Candidate and gold code is never executed here."""
import copy
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'bench'))
import benchlib as B  # noqa: E402
from common import check_benchmark_exclusion, load_data  # noqa: E402

POOL = ROOT / 'data/public/bench-pool'
RULES = ROOT / 'configs/bench/rules.toy.json'
TAXONOMY = ROOT / 'configs/bench/taxonomy.toy.json'


def run(*args):
    return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, capture_output=True, text=True)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.rules = B.read(RULES)
        self.tag = B.load_instance(POOL / 'toy-tag')
        self.quantity = B.load_instance(POOL / 'toy-quantity')

    def score(self, raw, inst=None, truncated=False, rules=None):
        return B.score_candidate(raw, truncated, inst or self.tag, rules or self.rules)

    def test_public_instances_are_valid_and_calibrated(self):
        for directory in B.instance_dirs(POOL):
            self.assertEqual(B.validate_instance(B.load_instance(directory), self.rules, B.read(TAXONOMY)), [], directory.name)

    def test_fence_truncation_and_repeated_blocks(self):
        block = '```python\n' + self.tag['gold'] + '```\n'
        fenced = self.score(block)
        self.assertFalse(fenced['fence_free'])
        self.assertTrue(fenced['oracle_pass'])
        self.assertFalse(fenced['auto_pass'])
        self.assertFalse(self.score(block + block)['single_block'])
        self.assertFalse(self.score(block, truncated=True)['not_truncated'])
        self.assertTrue(self.score('```python\n' + self.tag['gold'])['syntax_ok'])

    def test_reimplementing_the_api_fails_must_call(self):
        raw = ('import unittest\n\ndef normalize_tag(value):\n    return value.strip().lower()\n\n'
               'class T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(normalize_tag("  Ab C  "), "ab c")\n')
        result = self.score(raw)
        self.assertEqual(result['shadows_api'], ['normalize_tag'])
        self.assertEqual(result['must_call_missing'], ['normalize_tag'])
        self.assertFalse(result['auto_pass'])

    def test_ungrounded_call_and_keyword(self):
        raw = ('import unittest\nfrom toy_api import normalize_tag, helper\n\nclass T(unittest.TestCase):\n'
               '    def test_a(self):\n        helper()\n        self.assertEqual(normalize_tag(value="  Ab C  ", mode=1), "ab c")\n')
        result = self.score(raw)
        self.assertEqual(result['ungrounded_calls'], ['helper'])
        self.assertEqual(result['ungrounded_kwargs'], ['normalize_tag(mode=)'])
        self.assertFalse(result['static_pass'])

    def test_exception_flow_requires_the_configured_message(self):
        only_raises = ('import unittest\nfrom toy_api import parse_quantity\n\nclass T(unittest.TestCase):\n'
                       '    def test_a(self):\n        with self.assertRaises(ValueError):\n            parse_quantity("x")\n')
        result = self.score(only_raises, self.quantity)
        self.assertEqual(result['expect'][0]['hit'], 'miss')
        self.assertFalse(result['oracle_pass'])
        self.assertTrue(self.score(self.quantity['gold'], self.quantity)['auto_pass'])

    def test_value_without_target_is_partial(self):
        raw = ('import unittest\nfrom toy_api import normalize_tag\n\nclass T(unittest.TestCase):\n'
               '    def test_a(self):\n        got = normalize_tag("  Ab C  ")\n        self.assertEqual(got, "ab c")\n')
        result = self.score(raw)
        self.assertEqual(result['expect'][0]['hit'], 'value_only')
        self.assertFalse(result['oracle_pass'])

    def test_copied_reference_identity(self):
        inst = copy.deepcopy(self.tag)
        inst['task']['inputs']['reference'] = ('class Old(unittest.TestCase):\n    """\n    旧场景标题\n    """\n'
                                               '    script_id = "ref-123"\n')
        raw = ('import unittest\nfrom toy_api import normalize_tag\n\nclass T(unittest.TestCase):\n    """\n    旧场景标题\n    """\n'
               '    script_id = "ref-123"\n    def test_a(self):\n        self.assertEqual(normalize_tag("  Ab C  "), "ab c")\n')
        result = self.score(raw, inst)
        self.assertEqual(result['copied_identity'], ['ref-123', 'title:旧场景标题'])
        self.assertFalse(result['static_pass'])

    def test_framework_and_cleanup_rules(self):
        rules = dict(self.rules, required_methods=['setUp', 'tearDown'], super_calls={'tearDown': 'last'},
                     require_assert_message=True)
        inst = copy.deepcopy(self.tag)
        inst['oracle']['cleanup_required'] = ['release']
        raw = ('import unittest\nfrom toy_api import normalize_tag\n\nclass T(unittest.TestCase):\n'
               '    def setUp(self):\n        pass\n    def tearDown(self):\n        super().tearDown()\n        self._clean()\n'
               '    def _clean(self):\n        release()\n'
               '    def test_a(self):\n        self.assertEqual(normalize_tag("  Ab C  "), "ab c")\n')
        result = self.score(raw, inst, rules=rules)
        self.assertEqual(result['framework_failed'], ['assert_messages', 'super:tearDown:last'])
        self.assertEqual(result['cleanup_missing'], [])
        soft = self.score(raw, inst, rules=dict(rules, soft_checks=['assert_messages']))
        self.assertEqual(soft['soft_failed'], ['assert_messages'])

    def test_candidate_code_is_never_executed(self):
        raw = 'import sys\nsys.exit(3)\nraise SystemExit(4)\n'
        self.assertTrue(self.score(raw)['syntax_ok'])

    def test_missing_and_broken_candidates_count_as_failures(self):
        broken = self.score('def broken(:\n')
        self.assertFalse(broken['syntax_ok'])
        self.assertEqual(broken['must_call_missing'], ['normalize_tag'])
        missing = B.missing_result(self.tag, self.rules)
        self.assertTrue(missing['missing'])
        self.assertEqual(B.failure_reasons(missing), ['not generated'])


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for path in self.tmp.rglob('*'):
            os.chmod(path, stat.S_IRWXU)
        shutil.rmtree(self.tmp)

    def freeze(self, pool=POOL, version='v0.1'):
        return run('scripts/bench/build_suite.py', '--pool', pool, '--rules', RULES, '--taxonomy', TAXONOMY,
                   '--suites-root', self.tmp / 'suites', '--version', version)

    def test_freeze_verify_and_refuse_changes(self):
        result = self.freeze()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        suite = self.tmp / 'suites/v0.1'
        manifest = B.verify_suite(suite)
        self.assertEqual(manifest['counts']['instances'], 3)
        self.assertEqual(self.freeze().returncode, 1)
        gold = suite / 'instances/toy-tag/gold.py'
        os.chmod(gold, stat.S_IRWXU)
        gold.write_text(gold.read_text() + '# edited\n')
        with self.assertRaisesRegex(ValueError, 'modified after freezing'):
            B.verify_suite(suite)

    def test_draft_oracle_blocks_freezing(self):
        pool = self.tmp / 'pool'
        shutil.copytree(POOL, pool)
        oracle = json.loads((pool / 'toy-tag/oracle.json').read_text())
        oracle['status'] = 'draft'
        (pool / 'toy-tag/oracle.json').write_text(json.dumps(oracle))
        result = self.freeze(pool)
        self.assertEqual(result.returncode, 1)
        self.assertIn('still draft', result.stdout)

    def test_leakage_and_training_exclusion(self):
        self.assertEqual(self.freeze().returncode, 0)
        suite = self.tmp / 'suites/v0.1'
        rows = load_data(ROOT / 'data/public/toy.jsonl')
        clean = self.tmp / 'clean.jsonl'
        clean.write_text(''.join(json.dumps(r) + '\n' for r in rows if r['split'] == 'train'))
        self.assertEqual(run('scripts/bench/check_leakage.py', '--suite', suite, '--train', clean,
                             '--out', self.tmp / 'a.json').returncode, 0)
        leaked = [dict(r, split='train') for r in rows if r['id'] == 'toy-tag']
        bad = self.tmp / 'bad.jsonl'
        bad.write_text(''.join(json.dumps(r) + '\n' for r in leaked))
        result = run('scripts/bench/check_leakage.py', '--suite', suite, '--train', bad, '--out', self.tmp / 'b.json')
        self.assertEqual(result.returncode, 1)
        kinds = {x['kind'] for x in json.loads((self.tmp / 'b.json').read_text())['hard']}
        self.assertEqual(kinds, {'same_source_group', 'identical_answer'})
        with self.assertRaisesRegex(ValueError, 'overlaps the benchmark'):
            check_benchmark_exclusion(load_data(bad), [suite / 'manifest.json'])
        check_benchmark_exclusion(load_data(clean), [suite / 'manifest.json'])

    def test_import_pool_creates_a_draft_that_must_be_reviewed(self):
        candidates = self.tmp / 'candidates.jsonl'
        row = dict(next(r for r in load_data(ROOT / 'data/public/toy.jsonl', ()) if r['id'] == 'toy-tag'),
                   review_status='pending', tags={'flow': 'normal', 'domain': 'toy'})
        candidates.write_text(json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8')
        result = run('scripts/bench/import_pool.py', '--from', candidates, '--ids', 'toy-tag', '--pool', self.tmp / 'pool',
                     '--rules', RULES, '--taxonomy', TAXONOMY)
        self.assertEqual(result.returncode, 0, result.stderr)
        inst = B.load_instance(self.tmp / 'pool/toy-tag')
        self.assertEqual(inst['oracle']['status'], 'draft')
        self.assertEqual(inst['oracle']['must_call'], ['normalize_tag'])
        self.assertIn({'kind': 'assert_value', 'target': '', 'value': 'ab c'}, inst['oracle']['expect'])
        errors = B.validate_instance(inst, B.read(RULES), B.read(TAXONOMY))
        self.assertTrue(any('draft' in e for e in errors))
        self.assertTrue(any('review_status' in e for e in errors))

    def test_score_and_compare_runs(self):
        self.assertEqual(self.freeze().returncode, 0)
        suite = self.tmp / 'suites/v0.1'
        good, bad = self.tmp / 'good', self.tmp / 'bad'
        good.mkdir()
        bad.mkdir()
        for name in ('toy-tag', 'toy-quantity'):
            (good / (name + '.txt')).write_text((POOL / name / 'gold.py').read_text())
        (bad / 'toy-tag.txt').write_text('```python\n' + (POOL / 'toy-tag/gold.py').read_text() + '```\n')
        for source, arm in ((good, 'B1'), (bad, 'B0')):
            result = run('scripts/bench/import_run.py', '--suite', suite, '--from', source, '--experiment', 'E9', '--arm', arm,
                         '--out-root', self.tmp / 'runs')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(run('scripts/bench/score.py', '--run', self.tmp / 'runs/v0.1' / ('E9-' + arm)).returncode, 0)
        report = run('scripts/bench/compare.py', self.tmp / 'runs/v0.1/E9-B0', self.tmp / 'runs/v0.1/E9-B1')
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertIn('| E9-B1 | 2 | 0 | 0 | 0 |', report.stdout)
        self.assertIn('not generated', report.stdout)


class TrainingPoolTests(unittest.TestCase):
    def test_pool_may_span_files_and_hold_only_train(self):
        rows = load_data(ROOT / 'data/public/toy.jsonl')
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'a.jsonl', Path(directory) / 'b.jsonl'
            first.write_text(json.dumps(rows[0]) + '\n')
            other = dict(rows[1], split='train', source_group='g2')
            second.write_text(json.dumps(other) + '\n')
            self.assertEqual(len(load_data([first, second])), 2)
            with self.assertRaisesRegex(ValueError, 'duplicate id'):
                load_data([first, first])
            with self.assertRaisesRegex(ValueError, 'lacks required splits'):
                load_data(second, required_splits=('train', 'dev'))


if __name__ == '__main__':
    unittest.main()
