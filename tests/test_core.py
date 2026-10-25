import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from pilot.common import cgroup_state, read_json, verify_limits
from pilot.data import generate, validate, values
from pilot.runner import run_config, scenario_key


def temporary_directory():
    root = Path('tmp/test-work')
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=root)


class CorrectnessTests(unittest.TestCase):
    def setUp(self):
        self.seeds = {'a': 105, 'b': 205}
        keys = np.random.default_rng(4).permutation(257).astype('int64')
        self.frame = pd.DataFrame({'chave': keys, **{
            f'{t}{c}': values(keys, self.seeds[t], c) for t in ('a', 'b') for c in (1, 2)}})

    def test_exact_values_independent_of_order_and_chunks(self):
        self.assertTrue(validate(self.frame, 257, self.seeds, chunk_size=31)['ok'])

    def test_duplicate_crosses_chunk_boundary(self):
        self.frame.iloc[130] = self.frame.iloc[0]
        with self.assertRaisesRegex(AssertionError, 'Duplicate'):
            validate(self.frame, 257, self.seeds, chunk_size=31)

    def test_float_corruption_is_rejected(self):
        self.frame.loc[1, 'b2'] += .00000001
        with self.assertRaisesRegex(AssertionError, 'Value mismatch'):
            validate(self.frame, 257, self.seeds)

    def test_missing_row_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'Shape'):
            validate(self.frame.iloc[:-1], 257, self.seeds)

    def test_wrong_type_is_rejected(self):
        self.frame['chave'] = self.frame.chave.astype('float64')
        with self.assertRaisesRegex(AssertionError, 'Dtype'):
            validate(self.frame, 257, self.seeds)

    def test_outside_key_is_rejected(self):
        self.frame.loc[0, 'chave'] = -1
        with self.assertRaisesRegex(AssertionError, 'outside'):
            validate(self.frame, 257, self.seeds)

    def test_physical_data_shared_and_hash_checked(self):
        with temporary_directory() as root:
            m = generate(root, 4096, self.seeds, 8)
            a = pd.read_parquet(Path(m['directory']) / 'a')
            b = pd.read_parquet(Path(m['directory']) / 'b')
            self.assertEqual(len(m['files']), 16)
            self.assertFalse(np.array_equal(a.chave.values, b.chave.values))
            self.assertTrue(validate(a.merge(b, on='chave'), 4096, self.seeds)['ok'])
            self.assertEqual(generate(root, 4096, self.seeds, 8)['dataset_id'], m['dataset_id'])
            p = Path(m['directory']) / m['files'][0]['path']
            with p.open('ab') as stream:
                stream.write(b'corruption')
            with self.assertRaisesRegex(ValueError, 'corruption'):
                generate(root, 4096, self.seeds, 8)

    def test_fail_closed_without_docker_limits(self):
        with self.assertRaisesRegex(RuntimeError, 'CPU'):
            verify_limits({'cpu_limit': None, 'memory_limit_bytes': None})

    def test_host_cannot_be_presented_as_pilot(self):
        with self.assertRaisesRegex(ValueError, 'cannot be labelled'):
            run_config({'mode': 'pilot'}, 'bad', allow_host=True)


class AnalysisTests(unittest.TestCase):
    def test_incomplete_failures_excluded_and_paired(self):
        from pilot.analysis import analyze
        from pilot.common import write_json
        with temporary_directory() as temp:
            root = Path(temp)
            scenarios = [{'volume': 'medium', 'approach': 'pandas', 'workers': 0, 'partitions': 0},
                         {'volume': 'medium', 'approach': 'dask', 'workers': 2, 'partitions': 16}]
            meta = {'experiment_id': 'synthetic-unit-fixture', 'fingerprint': 'fixture',
                    'environment': 'UNIT TEST FIXTURE, NOT MEASUREMENTS', 'created_at': 'fixture',
                    'source_id': 'fixture', 'config': {'mode': 'unit-fixture', 'blocks': 5,
                    'scenarios': scenarios, 'volumes': {'medium': 10}}}
            write_json(root / 'experiment.json', meta)
            for i, (s, block, status, runtime) in enumerate([
                (scenarios[0], 1, 'success', 2.), (scenarios[0], 2, 'success', 4.),
                (scenarios[1], 1, 'success', 1.), (scenarios[1], 2, 'failed', 100.)]):
                write_json(root / 'raw' / str(i) / 'slot' / 'attempt' / 'record.json',
                           {**s, 'block': block, 'status': status, 'runtime_s': runtime,
                            'fingerprint': 'fixture', 'validation': {'ok': status == 'success'}, 'metrics': {}})
            result = analyze(root)
            table = pd.read_csv(root / 'processed' / 'summary.csv')
            self.assertEqual(result['failures'], 1)
            self.assertFalse(result['cp3_complete'])
            self.assertAlmostEqual(table.iloc[0].sample_std_runtime_s, 2**.5)
            self.assertEqual(table.iloc[1].mean_runtime_s, 1.)
            self.assertEqual(table.iloc[1].speedup, 2.)
            self.assertEqual(table.iloc[1].paired_blocks, 1)
            self.assertTrue(pd.isna(table.iloc[1].sample_std_runtime_s))


if __name__ == '__main__':
    unittest.main()
