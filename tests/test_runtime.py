"""Small fixtures only; no provider calls or experimental reruns."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from audit_framework import evaluation, repository
from audit_framework.cli import main, write_json

class RuntimeTests(unittest.TestCase):
    def test_repository_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ('../secret', '/etc/passwd', 'C:/secret', '.git/config', '.env', 'a\\b'):
                with self.assertRaises(ValueError): repository.repository_path(root, path)

    def test_read_and_search(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'calc.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
            (root/'.env').write_text('fixture=not_a_key', encoding='utf-8')
            self.assertEqual(repository.inventory(root), ['calc.py'])
            self.assertEqual(repository.search(root, 'return')[0]['line'], 2)
            self.assertTrue(repository.read_file(root, 'calc.py', 3)['truncated'])
            snapshot = repository.make_snapshot(root, 'fixture', 'Inspect addition', ['calc.py'])
            self.assertNotIn('verified', snapshot['evidence'][0])
            self.assertEqual(snapshot['history'][0]['evidence_ref'], ['source_1'])

    def test_localization_not_evidence_completion(self):
        result = evaluation.localization(['wrong.py'], ['correct.py'], evidence_record_complete=True)
        self.assertFalse(result['file_hit_1'])
        self.assertTrue(result['evidence_record_complete'])
        self.assertFalse(evaluation.localization([], ['correct.py'])['candidate_nonempty'])

    def test_missing_repair_is_not_failure(self):
        self.assertIsNone(evaluation.repair_outcome({'status': 'setup_failure'}, 'official_resolution'))
        self.assertIsNone(evaluation.repair_outcome({'status': 'completed', 'bounded_test_success': True}, 'official_resolution'))
        self.assertEqual(evaluation.repair_outcome({'status': 'completed', 'official_resolution': False}, 'official_resolution'), 0)

    def test_equation_two_direction(self):
        full = [{'task_id': str(i), 'trial_id': '1', 'status': 'completed', 'loc': value} for i, value in enumerate([1, 1, 0])]
        removed = [{**row, 'loc': value} for row, value in zip(full, [0, 1, 0])]
        result = evaluation.necessity(full, removed, outcome='loc')
        self.assertEqual((result['gains'], result['losses'], result['ties']), (1, 0, 2))
        self.assertAlmostEqual(result['necessity'], 1/3)
        removed[0]['status'] = 'provider_error'
        self.assertEqual(evaluation.necessity(full, removed, outcome='loc')['shared_incomplete'], 1)
        with self.assertRaises(ValueError): evaluation.necessity(full + full, removed, outcome='loc')

    def test_cli_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'snapshot.json'
            path.write_text(json.dumps({'task_id': 'fixture'}), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['validate', '--snapshot', str(path)]), 0)
            self.assertEqual(json.loads(out.getvalue())['status'], 'valid')
            with self.assertRaises(FileExistsError): write_json({}, path)

if __name__ == '__main__':
    unittest.main()
