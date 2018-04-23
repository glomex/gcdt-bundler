# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function
import os
import logging
import collections

import pytest
import mock
from gcdt_testtools.helpers import temp_folder, create_tempfile, cleanup_tempfiles
from gcdt_testtools import helpers
from gcdt_bundler.python_bundler import _get_cached_manylinux_wheel, \
    _have_correct_lambda_package_version, _site_packages_dir_in_venv, \
    _have_any_lambda_package_version, _get_installed_packages, \
    install_dependencies_with_pip, PipDependencyInstallationError

from . import here

import pip

log = logging.getLogger(__name__)


@pytest.mark.slow
@pytest.mark.parametrize('runtime', ['python2.7', 'python3.6'])
def test_install_dependencies_with_pip(runtime, temp_folder, cleanup_tempfiles):
    venv_dir = '%s/.gcdt/venv' % temp_folder[0]
    requirements_txt = create_tempfile('werkzeug\n')
    cleanup_tempfiles.append(requirements_txt)
    log.info(install_dependencies_with_pip(
        requirements_txt,
        runtime,
        venv_dir,
        False)
    )

    deps_dir = _site_packages_dir_in_venv(venv_dir)
    packages = os.listdir(deps_dir)
    for package in packages:
        log.debug(package)
    assert 'werkzeug' in packages


@pytest.mark.slow
@pytest.mark.parametrize('runtime', ['python2.7', 'python3.6'])
def test_install_dependencies_with_pip_not_found(runtime, temp_folder, cleanup_tempfiles):
    venv_dir = '%s/.gcdt/venv' % temp_folder[0]
    requirements_txt = create_tempfile('werkzeug\nnotfound==0.8.15\n')
    cleanup_tempfiles.append(requirements_txt)
    with pytest.raises(PipDependencyInstallationError):
        log.info(install_dependencies_with_pip(
            requirements_txt,
            runtime,
            venv_dir,
            False)
        )


'''
def test_bundle_revision(temp_folder):
    folders = [{
        'source': here('resources/simple_codedeploy/**'),
        'target': ''
    }]
    file_suffix = os.getenv('BUILD_TAG', '')
    if file_suffix:
        file_suffix = '_%s' % file_suffix
    expected_filename = '%s/tenkai-bundle%s.tar.gz' % (temp_folder[0], file_suffix)

    tarfile_name = bundle_revision(folders, outputpath=temp_folder[0])
    assert tarfile_name == expected_filename
    assert os.path.isfile(expected_filename)
    tar = tarfile.open(tarfile_name)
    actual_files = [t.name for t in tar.getmembers()]
    assert 'codedeploy_dev.conf' in actual_files
    assert 'gcdt_dev.json' in actual_files
    assert 'codedeploy/sample_code.txt' in actual_files
    assert 'codedeploy/sample_code2.txt' in actual_files
    assert 'codedeploy/folder/sample_code3.txt' in actual_files
'''


# test from Zappa
'''
def test_create_lambda_package():
    # mock the pip.get_installed_distributions() to include a known package in lambda_packages so that the code
    # for zipping pre-compiled packages gets called
    mock_installed_packages = {'psycopg2': '2.6.1'}
    with mock.patch('zappa.core.Zappa.get_installed_packages', return_value=mock_installed_packages):
        z = Zappa(runtime='python2.7')
        path = z.create_lambda_zip(handler_file=os.path.realpath(__file__))
        self.assertTrue(os.path.isfile(path))
        os.remove(path)
'''


def test_get_manylinux_python27():
    #z = Zappa(runtime='python2.7')
    assert _get_cached_manylinux_wheel('python2.7', 'cffi', '1.10.0') is not None
    assert _get_cached_manylinux_wheel('python2.7', 'derpderpderpderp', '0.0') is None

    '''
    # mock with a known manylinux wheel package so that code for downloading them gets invoked
    mock_installed_packages = { 'cffi' : '1.10.0' }
    with mock.patch('zappa.core.Zappa.get_installed_packages', return_value = mock_installed_packages):
        z = Zappa(runtime='python2.7')
        path = z.create_lambda_zip(handler_file=os.path.realpath(__file__))
        self.assertTrue(os.path.isfile(path))
        os.remove(path)
    '''


def test_get_manylinux_python36():
    #z = Zappa(runtime='python3.6')
    #self.assertIsNotNone(z.get_cached_manylinux_wheel('psycopg2', '2.7.1'))
    #self.assertIsNone(z.get_cached_manylinux_wheel('derpderpderpderp', '0.0'))
    assert _get_cached_manylinux_wheel('python3.6', 'psycopg2', '2.7.1') is not None
    assert _get_cached_manylinux_wheel('python3.6', 'derpderpderpderp', '0.0') is None

    '''
    # mock with a known manylinux wheel package so that code for downloading them gets invoked
    mock_installed_packages = {'psycopg2': '2.7.1'}
    with mock.patch('zappa.core.Zappa.get_installed_packages', return_value=mock_installed_packages):
        z = Zappa(runtime='python3.6')
        path = z.create_lambda_zip(handler_file=os.path.realpath(__file__))
        self.assertTrue(os.path.isfile(path))
        os.remove(path)
    '''


def test_should_use_lambda_packages():
    #z = Zappa(runtime='python2.7')

    assert _have_correct_lambda_package_version('python2.7', 'psycopg2', '2.6.1')
    assert _have_correct_lambda_package_version('python2.7', 'psycopg2', '2.7.1') is False
    #testing case-insensitivity with lambda_package MySQL-Python
    assert _have_correct_lambda_package_version('python2.7', 'mysql-python', '1.2.5')
    assert _have_correct_lambda_package_version('python2.7', 'mysql-python', '6.6.6') is False

    assert _have_any_lambda_package_version('python2.7', 'psycopg2')
    assert _have_any_lambda_package_version('python2.7', 'mysql-python')
    assert _have_any_lambda_package_version('python2.7', 'no_package') is False


def test_getting_installed_packages():
    #z = Zappa(runtime='python2.7')

    # mock pip packages call to be same as what our mocked site packages dir has
    mock_package = collections.namedtuple('mock_package', ['project_name', 'version'])
    mock_pip_installed_packages = [mock_package('super_package', '0.1')]

    with mock.patch('os.path.isdir', return_value=True):
        with mock.patch('os.listdir', return_value=['super_package']):
            #import pip  # this gets called in non-test Zappa mode
            with mock.patch('pip._internal.utils.misc.get_installed_distributions', return_value=mock_pip_installed_packages):
                assert _get_installed_packages('', '') == {'super_package' : '0.1'}
