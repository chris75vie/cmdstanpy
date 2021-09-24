"""utils test"""

import collections.abc
import contextlib
import json
import io
import os
import platform
import random
import subprocess
import shutil
import stat
import string
import tempfile
import unittest

import numpy as np
import pandas as pd

from cmdstanpy import _DOT_CMDSTAN, _DOT_CMDSTANPY, _TMPDIR
from cmdstanpy.model import CmdStanModel
from cmdstanpy.utils import (
    EXTENSION,
    MaybeDictToFilePath,
    SamplerProgress,
    TemporaryCopiedFile,
    check_sampler_csv,
    cmdstan_path,
    cmdstan_version_at,
    do_command,
    flatten_chains,
    get_latest_cmdstan,
    parse_method_vars,
    parse_rdump_value,
    parse_stan_vars,
    read_metric,
    rload,
    set_cmdstan_path,
    validate_cmdstan_path,
    validate_dir,
    windows_short_path,
    write_stan_json,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DATAFILES_PATH = os.path.join(HERE, 'data')
BERN_STAN = os.path.join(DATAFILES_PATH, 'bernoulli.stan')
BERN_DATA = os.path.join(DATAFILES_PATH, 'bernoulli.data.json')
BERN_EXE = os.path.join(DATAFILES_PATH, 'bernoulli' + EXTENSION)


class CmdStanPathTest(unittest.TestCase):
    def test_default_path(self):
        cur_value = None
        if 'CMDSTAN' in os.environ:
            cur_value = os.environ['CMDSTAN']
        try:
            if 'CMDSTAN' in os.environ:
                self.assertEqual(cmdstan_path(), os.environ['CMDSTAN'])
                path = os.environ['CMDSTAN']
                del os.environ['CMDSTAN']
                self.assertFalse('CMDSTAN' in os.environ)
                set_cmdstan_path(path)
                self.assertEqual(cmdstan_path(), path)
                self.assertTrue('CMDSTAN' in os.environ)
            else:
                cmdstan_dir = os.path.expanduser(
                    os.path.join('~', _DOT_CMDSTAN)
                )
                if not os.path.exists(cmdstan_dir):
                    cmdstan_dir = os.path.expanduser(
                        os.path.join('~', _DOT_CMDSTANPY)
                    )
                install_version = os.path.join(
                    cmdstan_dir, get_latest_cmdstan(cmdstan_dir)
                )
                self.assertTrue(
                    os.path.samefile(cmdstan_path(), install_version)
                )
                self.assertTrue('CMDSTAN' in os.environ)
        finally:
            if cur_value is not None:
                os.environ['CMDSTAN'] = cur_value
            else:
                if 'CMDSTAN' in os.environ:
                    del os.environ['CMDSTAN']

    def test_non_spaces_location(self):
        with tempfile.TemporaryDirectory(
            prefix="cmdstan_tests", dir=_TMPDIR
        ) as tmpdir:
            good_path = os.path.join(tmpdir, 'good_dir')
            with TemporaryCopiedFile(good_path) as (pth, is_changed):
                self.assertEqual(pth, good_path)
                self.assertFalse(is_changed)

            # prepare files for test
            bad_path = os.path.join(tmpdir, 'bad dir')
            os.makedirs(bad_path, exist_ok=True)
            stan = os.path.join(DATAFILES_PATH, 'bernoulli.stan')
            stan_bad = os.path.join(bad_path, 'bad name.stan')
            shutil.copy(stan, stan_bad)

            stan_copied = None
            try:
                with TemporaryCopiedFile(stan_bad) as (pth, is_changed):
                    stan_copied = pth
                    self.assertTrue(os.path.exists(stan_copied))
                    self.assertTrue(' ' not in stan_copied)
                    self.assertTrue(is_changed)
                    raise RuntimeError
            except RuntimeError:
                pass

            if platform.system() != 'Windows':
                self.assertFalse(os.path.exists(stan_copied))

            # cleanup after test
            shutil.rmtree(bad_path, ignore_errors=True)

    def test_set_path(self):
        if 'CMDSTAN' in os.environ:
            self.assertEqual(cmdstan_path(), os.environ['CMDSTAN'])
        else:
            cmdstan_dir = os.path.expanduser(os.path.join('~', _DOT_CMDSTAN))
            if not os.path.exists(cmdstan_dir):
                cmdstan_dir = os.path.expanduser(
                    os.path.join('~', _DOT_CMDSTANPY)
                )
            install_version = os.path.join(
                cmdstan_dir, get_latest_cmdstan(cmdstan_dir)
            )
            set_cmdstan_path(install_version)
            self.assertEqual(install_version, cmdstan_path())
            self.assertEqual(install_version, os.environ['CMDSTAN'])

    def test_validate_path(self):
        if 'CMDSTAN' in os.environ:
            install_version = os.environ.get('CMDSTAN')
        else:
            cmdstan_dir = os.path.expanduser(os.path.join('~', _DOT_CMDSTAN))
            if not os.path.exists(cmdstan_dir):
                cmdstan_dir = os.path.expanduser(
                    os.path.join('~', _DOT_CMDSTANPY)
                )

            install_version = os.path.join(
                cmdstan_dir, get_latest_cmdstan(cmdstan_dir)
            )

        set_cmdstan_path(install_version)
        validate_cmdstan_path(install_version)
        path_foo = os.path.abspath(os.path.join('releases', 'foo'))
        with self.assertRaisesRegex(ValueError, 'no such CmdStan directory'):
            validate_cmdstan_path(path_foo)
        folder_name = ''.join(
            random.choice(string.ascii_letters) for _ in range(10)
        )
        while os.path.exists(folder_name):
            folder_name = ''.join(
                random.choice(string.ascii_letters) for _ in range(10)
            )
        os.makedirs(folder_name)
        path_test = os.path.abspath(folder_name)
        with self.assertRaisesRegex(ValueError, 'no CmdStan binaries'):
            validate_cmdstan_path(path_test)
        shutil.rmtree(folder_name)

    def test_validate_dir(self):
        with tempfile.TemporaryDirectory(
            prefix="cmdstan_tests", dir=_TMPDIR
        ) as tmpdir:
            path = os.path.join(tmpdir, 'cmdstan-M.m.p')
            self.assertFalse(os.path.exists(path))
            validate_dir(path)
            self.assertTrue(os.path.exists(path))

            _, file = tempfile.mkstemp(dir=_TMPDIR)
            with self.assertRaisesRegex(Exception, 'File exists'):
                validate_dir(file)

            if platform.system() != 'Windows':
                with self.assertRaisesRegex(
                    Exception, 'Cannot create directory'
                ):
                    dir = tempfile.mkdtemp(dir=_TMPDIR)
                    os.chmod(dir, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                    validate_dir(os.path.join(dir, 'cmdstan-M.m.p'))

    def test_munge_cmdstan_versions(self):
        with tempfile.TemporaryDirectory(
            prefix="cmdstan_tests", dir=_TMPDIR
        ) as tmpdir:
            tdir = os.path.join(tmpdir, 'tmpdir_xxx')
            os.makedirs(tdir)
            os.makedirs(os.path.join(tdir, 'cmdstan-2.22.0-rc1'))
            os.makedirs(os.path.join(tdir, 'cmdstan-2.22.0-rc2'))
            self.assertEqual(get_latest_cmdstan(tdir), 'cmdstan-2.22.0-rc2')

            os.makedirs(os.path.join(tdir, 'cmdstan-2.22.0'))
            self.assertEqual(get_latest_cmdstan(tdir), 'cmdstan-2.22.0')

    def test_cmdstan_version_at(self):
        cmdstan_path()  # sets os.environ['CMDSTAN']
        self.assertFalse(cmdstan_version_at(99, 99))


class DataFilesTest(unittest.TestCase):
    def test_dict_to_file(self):
        file_good = os.path.join(DATAFILES_PATH, 'bernoulli_output_1.csv')
        dict_good = {'a': 0.5}
        created_tmp = None
        with MaybeDictToFilePath(file_good, dict_good) as (fg1, fg2):
            self.assertTrue(os.path.exists(fg1))
            self.assertTrue(os.path.exists(fg2))
            with open(fg2) as fg2_d:
                self.assertEqual(json.load(fg2_d), dict_good)
            created_tmp = fg2
        self.assertTrue(os.path.exists(file_good))
        self.assertFalse(os.path.exists(created_tmp))

        with self.assertRaises(ValueError):
            with MaybeDictToFilePath(123, dict_good) as (fg1, fg2):
                pass

    def test_write_stan_json(self):
        def cmp(d1, d2):
            self.assertEqual(d1.keys(), d2.keys())
            for k in d1:
                data_1 = d1[k]
                data_2 = d2[k]
                if isinstance(data_2, collections.abc.Collection):
                    data_2 = np.asarray(data_2).tolist()

                self.assertEqual(data_1, data_2)

        dict_list = {'a': [1.0, 2.0, 3.0]}
        file_list = os.path.join(_TMPDIR, 'list.json')
        write_stan_json(file_list, dict_list)
        with open(file_list) as fd:
            cmp(json.load(fd), dict_list)

        arr = np.repeat(3, 4)
        dict_vec = {'a': arr}
        file_vec = os.path.join(_TMPDIR, 'vec.json')
        write_stan_json(file_vec, dict_vec)
        with open(file_vec) as fd:
            cmp(json.load(fd), dict_vec)

        dict_bool = {'a': False}
        file_bool = os.path.join(_TMPDIR, 'bool.json')
        write_stan_json(file_bool, dict_bool)
        with open(file_bool) as fd:
            cmp(json.load(fd), {'a': 0})

        dict_none = {'a': None}
        file_none = os.path.join(_TMPDIR, 'none.json')
        write_stan_json(file_none, dict_none)
        with open(file_none) as fd:
            cmp(json.load(fd), dict_none)

        series = pd.Series(arr)
        dict_vec_pd = {'a': series}
        file_vec_pd = os.path.join(_TMPDIR, 'vec_pd.json')
        write_stan_json(file_vec_pd, dict_vec_pd)
        with open(file_vec_pd) as fd:
            cmp(json.load(fd), dict_vec_pd)

        df_vec = pd.DataFrame(dict_list)
        file_pd = os.path.join(_TMPDIR, 'pd.json')
        write_stan_json(file_pd, df_vec)
        with open(file_pd) as fd:
            cmp(json.load(fd), dict_list)

        dict_zero_vec = {'a': []}
        file_zero_vec = os.path.join(_TMPDIR, 'empty_vec.json')
        write_stan_json(file_zero_vec, dict_zero_vec)
        with open(file_zero_vec) as fd:
            cmp(json.load(fd), dict_zero_vec)

        dict_zero_matrix = {'a': [[], [], []]}
        file_zero_matrix = os.path.join(_TMPDIR, 'empty_matrix.json')
        write_stan_json(file_zero_matrix, dict_zero_matrix)
        with open(file_zero_matrix) as fd:
            cmp(json.load(fd), dict_zero_matrix)

        arr = np.zeros(shape=(5, 0))
        dict_zero_matrix = {'a': arr}
        file_zero_matrix = os.path.join(_TMPDIR, 'empty_matrix.json')
        write_stan_json(file_zero_matrix, dict_zero_matrix)
        with open(file_zero_matrix) as fd:
            cmp(json.load(fd), dict_zero_matrix)

        arr = np.zeros(shape=(2, 3, 4))
        self.assertTrue(isinstance(arr, np.ndarray))
        self.assertEqual(arr.shape, (2, 3, 4))

        dict_3d_matrix = {'a': arr}
        file_3d_matrix = os.path.join(_TMPDIR, '3d_matrix.json')
        write_stan_json(file_3d_matrix, dict_3d_matrix)
        with open(file_3d_matrix) as fd:
            cmp(json.load(fd), dict_3d_matrix)

        scalr = np.int32(1)
        self.assertTrue(type(scalr).__module__ == 'numpy')
        dict_scalr = {'a': scalr}
        file_scalr = os.path.join(_TMPDIR, 'scalr.json')
        write_stan_json(file_scalr, dict_scalr)
        with open(file_scalr) as fd:
            cmp(json.load(fd), dict_scalr)

    def test_write_stan_json_bad(self):
        file_bad = os.path.join(_TMPDIR, 'bad.json')

        dict_badtype = {'a': 'a string'}
        with self.assertRaises(TypeError):
            write_stan_json(file_bad, dict_badtype)

        dict_badtype_nested = {'a': ['a string']}
        with self.assertRaises(ValueError):
            write_stan_json(file_bad, dict_badtype_nested)

        dict_inf = {'a': [np.inf]}
        with self.assertRaises(ValueError):
            write_stan_json(file_bad, dict_inf)

        dict_nan = {'a': np.nan}
        with self.assertRaises(ValueError):
            write_stan_json(file_bad, dict_nan)


class ReadStanCsvTest(unittest.TestCase):
    def test_check_sampler_csv_1(self):
        csv_good = os.path.join(DATAFILES_PATH, 'bernoulli_output_1.csv')
        dict = check_sampler_csv(
            path=csv_good,
            is_fixed_param=False,
            iter_warmup=100,
            iter_sampling=10,
            thin=1,
        )
        self.assertEqual('bernoulli_model', dict['model'])
        self.assertEqual(10, dict['num_samples'])
        self.assertEqual(10, dict['draws_sampling'])
        self.assertEqual(8, len(dict['column_names']))

        with self.assertRaisesRegex(
            ValueError, 'config error, expected thin = 2'
        ):
            check_sampler_csv(
                path=csv_good, iter_warmup=100, iter_sampling=20, thin=2
            )
        with self.assertRaisesRegex(
            ValueError, 'config error, expected save_warmup'
        ):
            check_sampler_csv(
                path=csv_good,
                iter_warmup=100,
                iter_sampling=10,
                save_warmup=True,
            )
        with self.assertRaisesRegex(ValueError, 'expected 1000 draws'):
            check_sampler_csv(path=csv_good, iter_warmup=100)

    def test_check_sampler_csv_2(self):
        csv_bad = os.path.join(DATAFILES_PATH, 'no_such_file.csv')
        with self.assertRaises(Exception):
            check_sampler_csv(csv_bad)

    def test_check_sampler_csv_3(self):
        csv_bad = os.path.join(DATAFILES_PATH, 'output_bad_cols.csv')
        with self.assertRaisesRegex(Exception, '8 items'):
            check_sampler_csv(csv_bad)

    def test_check_sampler_csv_4(self):
        csv_bad = os.path.join(DATAFILES_PATH, 'output_bad_rows.csv')
        with self.assertRaisesRegex(Exception, 'found 9'):
            check_sampler_csv(csv_bad)

    def test_check_sampler_csv_metric_1(self):
        csv_bad = os.path.join(DATAFILES_PATH, 'output_bad_metric_1.csv')
        with self.assertRaisesRegex(Exception, 'expecting metric'):
            check_sampler_csv(csv_bad)

    def test_check_sampler_csv_metric_2(self):
        csv_bad = os.path.join(DATAFILES_PATH, 'output_bad_metric_2.csv')
        with self.assertRaisesRegex(Exception, 'invalid step size'):
            check_sampler_csv(csv_bad)

    def test_check_sampler_csv_metric_3(self):
        csv_bad = os.path.join(DATAFILES_PATH, 'output_bad_metric_3.csv')
        with self.assertRaisesRegex(
            Exception, 'invalid or missing mass matrix specification'
        ):
            check_sampler_csv(csv_bad)

    def test_check_sampler_csv_metric_4(self):
        csv_bad = os.path.join(DATAFILES_PATH, 'output_bad_metric_4.csv')
        with self.assertRaisesRegex(
            Exception, 'invalid or missing mass matrix specification'
        ):
            check_sampler_csv(csv_bad)

    def test_check_sampler_csv_thin(self):
        stan = os.path.join(DATAFILES_PATH, 'bernoulli.stan')
        bern_model = CmdStanModel(stan_file=stan)
        bern_model.compile()
        jdata = os.path.join(DATAFILES_PATH, 'bernoulli.data.json')
        bern_fit = bern_model.sample(
            data=jdata,
            chains=1,
            parallel_chains=1,
            seed=12345,
            iter_sampling=490,
            iter_warmup=490,
            thin=7,
            max_treedepth=11,
            adapt_delta=0.98,
        )
        csv_file = bern_fit.runset.csv_files[0]
        dict = check_sampler_csv(
            path=csv_file,
            is_fixed_param=False,
            iter_sampling=490,
            iter_warmup=490,
            thin=7,
        )
        self.assertEqual(dict['num_samples'], 490)
        self.assertEqual(dict['thin'], 7)
        self.assertEqual(dict['draws_sampling'], 70)
        self.assertEqual(dict['seed'], 12345)
        self.assertEqual(dict['max_depth'], 11)
        self.assertEqual(dict['delta'], 0.98)

        with self.assertRaisesRegex(ValueError, 'config error'):
            check_sampler_csv(
                path=csv_file,
                is_fixed_param=False,
                iter_sampling=490,
                iter_warmup=490,
                thin=9,
            )
        with self.assertRaisesRegex(ValueError, 'expected 490 draws, found 70'):
            check_sampler_csv(
                path=csv_file,
                is_fixed_param=False,
                iter_sampling=490,
                iter_warmup=490,
            )


class ReadMetricTest(unittest.TestCase):
    def test_metric_json_vec(self):
        metric_file = os.path.join(DATAFILES_PATH, 'metric_diag.data.json')
        dims = read_metric(metric_file)
        self.assertEqual(1, len(dims))
        self.assertEqual(3, dims[0])

    def test_metric_json_matrix(self):
        metric_file = os.path.join(DATAFILES_PATH, 'metric_dense.data.json')
        dims = read_metric(metric_file)
        self.assertEqual(2, len(dims))
        self.assertEqual(dims[0], dims[1])

    def test_metric_rdump_vec(self):
        metric_file = os.path.join(DATAFILES_PATH, 'metric_diag.data.R')
        dims = read_metric(metric_file)
        self.assertEqual(1, len(dims))
        self.assertEqual(3, dims[0])

    def test_metric_rdump_matrix(self):
        metric_file = os.path.join(DATAFILES_PATH, 'metric_dense.data.R')
        dims = read_metric(metric_file)
        self.assertEqual(2, len(dims))
        self.assertEqual(dims[0], dims[1])

    def test_metric_json_bad(self):
        metric_file = os.path.join(DATAFILES_PATH, 'metric_bad.data.json')
        with self.assertRaisesRegex(
            Exception, 'bad or missing entry "inv_metric"'
        ):
            read_metric(metric_file)

    def test_metric_rdump_bad_1(self):
        metric_file = os.path.join(DATAFILES_PATH, 'metric_bad_1.data.R')
        with self.assertRaisesRegex(
            Exception, 'bad or missing entry "inv_metric"'
        ):
            read_metric(metric_file)

    def test_metric_rdump_bad_2(self):
        metric_file = os.path.join(DATAFILES_PATH, 'metric_bad_2.data.R')
        with self.assertRaisesRegex(
            Exception, 'bad or missing entry "inv_metric"'
        ):
            read_metric(metric_file)

    def test_metric_missing(self):
        metric_file = os.path.join(DATAFILES_PATH, 'no_such_file.json')
        with self.assertRaisesRegex(Exception, 'No such file or directory'):
            read_metric(metric_file)


# pylint: disable=no-self-use
class WindowsShortPath(unittest.TestCase):
    def test_windows_short_path_directory(self):
        if platform.system() != 'Windows':
            return
        with tempfile.TemporaryDirectory(
            prefix="cmdstan_tests", dir=_TMPDIR
        ) as tmpdir:
            original_path = os.path.join(tmpdir, 'new path')
            os.makedirs(original_path, exist_ok=True)
            assert os.path.exists(original_path)
            assert ' ' in original_path
            short_path = windows_short_path(original_path)
            assert os.path.exists(short_path)
            assert original_path != short_path
            assert ' ' not in short_path

    def test_windows_short_path_file(self):
        if platform.system() != 'Windows':
            return
        with tempfile.TemporaryDirectory(
            prefix="cmdstan_tests", dir=_TMPDIR
        ) as tmpdir:
            original_path = os.path.join(tmpdir, 'new path', 'my_file.csv')
            os.makedirs(os.path.split(original_path)[0], exist_ok=True)
            assert os.path.exists(os.path.split(original_path)[0])
            assert ' ' in original_path
            assert os.path.splitext(original_path)[1] == '.csv'
            short_path = windows_short_path(original_path)
            assert os.path.exists(os.path.split(short_path)[0])
            assert original_path != short_path
            assert ' ' not in short_path
            assert os.path.splitext(short_path)[1] == '.csv'

    def test_windows_short_path_file_with_space(self):
        """Test that the function doesn't touch filename."""
        if platform.system() != 'Windows':
            return
        with tempfile.TemporaryDirectory(
            prefix="cmdstan_tests", dir=_TMPDIR
        ) as tmpdir:
            original_path = os.path.join(tmpdir, 'new path', 'my file.csv')
            os.makedirs(os.path.split(original_path)[0], exist_ok=True)
            assert os.path.exists(os.path.split(original_path)[0])
            assert ' ' in original_path
            short_path = windows_short_path(original_path)
            assert os.path.exists(os.path.split(short_path)[0])
            assert original_path != short_path
            assert ' ' in short_path
            assert os.path.splitext(short_path)[1] == '.csv'


class RloadTest(unittest.TestCase):
    def test_rload_metric(self):
        dfile = os.path.join(DATAFILES_PATH, 'metric_diag.data.R')
        data_dict = rload(dfile)
        self.assertEqual(data_dict['inv_metric'].shape, (3,))

        dfile = os.path.join(DATAFILES_PATH, 'metric_dense.data.R')
        data_dict = rload(dfile)
        self.assertEqual(data_dict['inv_metric'].shape, (3, 3))

    def test_rload_data(self):
        dfile = os.path.join(DATAFILES_PATH, 'rdump_test.data.R')
        data_dict = rload(dfile)
        self.assertEqual(data_dict['N'], 128)
        self.assertEqual(data_dict['M'], 2)
        self.assertEqual(data_dict['x'].shape, (128, 2))

    def test_rload_jags_data(self):
        dfile = os.path.join(DATAFILES_PATH, 'rdump_jags.data.R')
        data_dict = rload(dfile)
        self.assertEqual(data_dict['N'], 128)
        self.assertEqual(data_dict['M'], 2)
        self.assertEqual(data_dict['y'].shape, (128,))

    def test_rload_wrong_data(self):
        dfile = os.path.join(DATAFILES_PATH, 'metric_diag.data.json')
        data_dict = rload(dfile)
        self.assertEqual(data_dict, None)

    def test_rload_bad_data_1(self):
        dfile = os.path.join(DATAFILES_PATH, 'rdump_bad_1.data.R')
        with self.assertRaises(ValueError):
            rload(dfile)

    def test_rload_bad_data_2(self):
        dfile = os.path.join(DATAFILES_PATH, 'rdump_bad_2.data.R')
        with self.assertRaises(ValueError):
            rload(dfile)

    def test_rload_bad_data_3(self):
        dfile = os.path.join(DATAFILES_PATH, 'rdump_bad_3.data.R')
        with self.assertRaises(ValueError):
            rload(dfile)

    def test_parse_rdump_value(self):
        struct1 = (
            'structure(c(1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16),.Dim=c(2,8))'
        )
        v_struct1 = parse_rdump_value(struct1)
        self.assertEqual(v_struct1.shape, (2, 8))
        self.assertEqual(v_struct1[1, 0], 2)
        self.assertEqual(v_struct1[0, 7], 15)

        struct2 = (
            'structure(c(1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16),.Dim=c(1,16))'
        )
        v_struct2 = parse_rdump_value(struct2)
        self.assertEqual(v_struct2.shape, (1, 16))

        struct3 = (
            'structure(c(1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16),.Dim=c(8,2))'
        )
        v_struct3 = parse_rdump_value(struct3)
        self.assertEqual(v_struct3.shape, (8, 2))
        self.assertEqual(v_struct3[1, 0], 2)
        self.assertEqual(v_struct3[7, 0], 8)
        self.assertEqual(v_struct3[0, 1], 9)
        self.assertEqual(v_struct3[6, 1], 15)


class ParseVarsTest(unittest.TestCase):
    def test_parse_empty(self):
        x = []
        sampler_vars = parse_method_vars(x)
        self.assertEqual(len(sampler_vars), 0)
        stan_vars_dims, stan_vars_cols = parse_stan_vars(x)
        self.assertEqual(len(stan_vars_dims), 0)
        self.assertEqual(len(stan_vars_cols), 0)

    def test_parse_missing(self):
        with self.assertRaises(ValueError):
            parse_method_vars(None)
        with self.assertRaises(ValueError):
            parse_stan_vars(None)

    def test_parse_method_vars(self):
        x = [
            'lp__',
            'accept_stat__',
            'stepsize__',
            'treedepth__',
            'n_leapfrog__',
            'divergent__',
            'energy__',
            'theta[1]',
            'theta[2]',
            'theta[3]',
            'theta[4]',
            'z_init[1]',
            'z_init[2]',
        ]
        vars_dict = parse_method_vars(x)
        self.assertEqual(len(vars_dict), 7)
        self.assertEqual(vars_dict['lp__'], (0,))
        self.assertEqual(vars_dict['stepsize__'], (2,))

    def test_parse_scalars(self):
        x = ['lp__', 'foo']
        dims_map, cols_map = parse_stan_vars(x)
        self.assertEqual(len(dims_map), 1)
        self.assertEqual(dims_map['foo'], ())
        self.assertEqual(len(cols_map), 1)
        self.assertEqual(cols_map['foo'], (1,))

        dims_map = {}
        cols_map = {}
        x = ['lp__', 'foo1', 'foo2']
        dims_map, cols_map = parse_stan_vars(x)
        self.assertEqual(len(dims_map), 2)
        self.assertEqual(dims_map['foo1'], ())
        self.assertEqual(dims_map['foo2'], ())
        self.assertEqual(len(cols_map), 2)
        self.assertEqual(cols_map['foo1'], (1,))
        self.assertEqual(cols_map['foo2'], (2,))

    def test_parse_containers(self):
        # demonstrates flaw in shortcut to get container dims
        x = [
            'lp__',
            'accept_stat__',
            'foo',
            'phi[1]',
            'phi[2]',
            'phi[3]',
            'phi[10]',
            'bar',
        ]
        dims_map, cols_map = parse_stan_vars(x)
        self.assertEqual(len(dims_map), 3)
        self.assertEqual(dims_map['foo'], ())
        self.assertEqual(dims_map['phi'], (10,))  # sic
        self.assertEqual(dims_map['bar'], ())
        self.assertEqual(len(cols_map), 3)
        self.assertEqual(cols_map['foo'], (2,))
        self.assertEqual(
            cols_map['phi'],
            (
                3,
                4,
                5,
                6,
            ),
        )
        self.assertEqual(cols_map['bar'], (7,))

        x = [
            'lp__',
            'accept_stat__',
            'foo',
            'phi[1]',
            'phi[2]',
            'phi[3]',
            'phi[10,10]',
            'bar',
        ]
        dims_map = {}
        cols_map = {}
        dims_map, cols_map = parse_stan_vars(x)
        self.assertEqual(len(dims_map), 3)
        self.assertEqual(
            dims_map['phi'],
            (
                10,
                10,
            ),
        )
        self.assertEqual(len(cols_map), 3)
        self.assertEqual(
            cols_map['phi'],
            (
                3,
                4,
                5,
                6,
            ),
        )

        x = [
            'lp__',
            'accept_stat__',
            'foo',
            'phi[10,10,10]',
        ]
        dims_map = {}
        cols_map = {}
        dims_map, cols_map = parse_stan_vars(x)
        self.assertEqual(len(dims_map), 2)
        self.assertEqual(
            dims_map['phi'],
            (
                10,
                10,
                10,
            ),
        )
        self.assertEqual(len(cols_map), 2)
        self.assertEqual(cols_map['phi'], (3,))


class DoCommandTest(unittest.TestCase):
    def test_good(self):
        sys_stdout = io.StringIO()
        with contextlib.redirect_stdout(sys_stdout):
            retcode = do_command(cmd=['ls'], cwd=HERE, show_console=True)
        console = sys_stdout.getvalue()
        self.assertTrue('test_utils.py' in console)
        self.assertEqual(retcode, 0)

        sink = io.StringIO()
        retcode = do_command(cmd=['ls'], cwd=HERE, sink=sink)
        sunk = sink.getvalue()
        self.assertTrue('test_utils.py' in sunk)
        self.assertEqual(retcode, 0)

        nout = io.StringIO()
        with contextlib.redirect_stdout(nout):
            retcode = do_command(cmd=['ls'], cwd=HERE, show_console=False)
        console = nout.getvalue()
        self.assertEqual(len(console), 0)
        self.assertEqual(retcode, 0)

    def test_exit(self):
        sys_stdout = io.StringIO()
        with contextlib.redirect_stdout(sys_stdout):
            args = ['bash', '/bin/junk']
            with self.assertRaises(RuntimeError):
                do_command(args, HERE)


class FlattenTest(unittest.TestCase):
    def test_good(self):
        array_3d = np.empty((200, 4, 4))
        vals = [1.0, 2.0, 3.0, 4.0]
        pos = [(0, 0, 0), (0, 1, 1), (0, 2, 2), (0, 3, 3)]
        draws, chains, cols = zip(*pos)
        array_3d[draws, chains, cols] = vals
        flattened = flatten_chains(array_3d)

        self.assertEqual(flattened.shape, (800, 4))
        self.assertEqual(flattened[0, 0], 1.0)
        self.assertEqual(flattened[200, 1], 2.0)
        self.assertEqual(flattened[400, 2], 3.0)
        self.assertEqual(flattened[600, 3], 4.0)

    def test_bad(self):
        array_2d = np.empty((200, 4))
        with self.assertRaisesRegex(ValueError, 'Expecting 3D array'):
            flatten_chains(array_2d)


class SamplerProgressTest(unittest.TestCase):
    def test_progress_reporter(self):
        CmdStanModel(model_name='bern', stan_file=BERN_STAN)
        cmd = [
            BERN_EXE,
            'data',
            f'file={BERN_DATA}',
            'method=sample',
            'num_warmup=10000',
            'num_samples=10000',
            'output',
            'refresh=2000',
        ]
        fd_stdout = io.StringIO()
        proc = subprocess.Popen(
            cmd,
            bufsize=1,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # avoid buffer overflow
            env=os.environ,
            universal_newlines=True,
        )
        prog_rprt = SamplerProgress(
            proc=proc,
            fd=fd_stdout,
            show_pbar=True,
            show_console=False,
            iter_total=20000,
            chain=1,
        )
        self.assertEqual(prog_rprt.progress, 'Not started')
        self.assertEqual(prog_rprt.phase, 'Not started')
        iters = 0
        for j in iter(prog_rprt):
            iters += 1
            if iters == 1:
                self.assertEqual(j, 1)
                self.assertEqual(prog_rprt.phase, 'Warmup')
                self.assertEqual(
                    prog_rprt.progress,
                    'Iteration:     1 / 20000 [  0%]  (Warmup)',
                )
            elif iters == 6:
                self.assertEqual(j, 10000)
                self.assertEqual(prog_rprt.phase, 'Warmup')
                self.assertEqual(
                    prog_rprt.progress,
                    'Iteration: 10000 / 20000 [ 50%]  (Warmup)',
                )
            elif iters == 7:
                self.assertEqual(j, 10001)
                self.assertEqual(prog_rprt.phase, 'Sampling')
                self.assertEqual(
                    prog_rprt.progress,
                    'Iteration: 10001 / 20000 [ 50%]  (Sampling)',
                )
        self.assertEqual(prog_rprt._iter, 20000)
        self.assertEqual(
            prog_rprt.progress, 'Iteration: 20000 / 20000 [100%]  (Sampling)'
        )
        proc.communicate()
        self.assertEqual(proc.returncode, 0)


if __name__ == '__main__':
    unittest.main()
