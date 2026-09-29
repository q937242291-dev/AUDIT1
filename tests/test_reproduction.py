"""Negative cases and estimator identities, not synthetic empirical results."""
import importlib.util,math,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('controlled',Path(__file__).resolve().parents[1]/'scripts/reproduce_controlled_experiments.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
class ReproductionTests(unittest.TestCase):
    def test_missing_is_not_failure(self):
        for value in ['',None,'NA','N/A','nan']:
            with self.assertRaises(ValueError):c.num(value)
    def test_binary_validation(self):
        self.assertEqual(c.binary('false'),0)
        with self.assertRaises(ValueError):c.binary(2)
    def test_duplicate_pairs_rejected(self):
        with self.assertRaises(ValueError):c.unique_index([{'id':1},{'id':1}],['id'])
    def test_discordant_pair_test(self):
        r=c.paired([0,0,1,1],[1,1,0,1]);self.assertEqual((r['gain'],r['loss'],r['ties']),(2,1,1));self.assertEqual(r['delta'],.25)
        self.assertEqual(c.paired([1,0],[1,0])['exact_mcnemar_p'],1)
    def test_wilson_bounds(self):
        self.assertAlmostEqual(c.wilson(0,60)[0],0)
        self.assertAlmostEqual(c.wilson(60,60)[1],1)
    def test_completed_not_scheduled(self):
        self.assertNotAlmostEqual(19/58,19/60);self.assertEqual(round(34/60*100,1),56.7)
if __name__=='__main__':unittest.main()
