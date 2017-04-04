# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function
import os
import io
import textwrap
import logging
from zipfile import ZipFile
from tempfile import mkdtemp

import pytest
from gcdt_testtools.helpers import temp_folder, create_tempfile, get_size, \
    check_npm_precondition, cleanup_tempfiles
from gcdt_testtools import helpers

from gcdt_bundler.bundler import _make_tar_file, _files_to_bundle, \
    bundle_revision, _install_dependencies_with_pip, get_packages_to_ignore, \
    _install_dependencies_with_npm, cleanup_folder, _get_zipped_file, prebundle
from . import here

log = logging.getLogger(__name__)


def test_make_tar_file(temp_folder):
    # _make_tar_file implements bundle
    codedeploy = here('resources/simple_codedeploy/codedeploy')
    file_suffix = os.getenv('BUILD_TAG', '')
    expected_filename = '%s/tenkai-bundle%s.tar.gz' % (temp_folder[0], file_suffix)

    tarfile_name = _make_tar_file(path=codedeploy,
                                  outputpath=temp_folder[0])
    assert tarfile_name == expected_filename
    assert os.path.isfile(expected_filename)


def test_bundle_revision(temp_folder):
    os.chdir(here('resources/simple_codedeploy'))
    file_suffix = os.getenv('BUILD_TAG', '')
    expected_filename = '%s/tenkai-bundle%s.tar.gz' % (temp_folder[0], file_suffix)

    tarfile_name = bundle_revision(outputpath=temp_folder[0])
    assert tarfile_name == expected_filename
    assert os.path.isfile(expected_filename)


def test_files_to_bundle():
    codedeploy = here('resources/simple_codedeploy/codedeploy')
    expected = ['sample_code.txt', 'sample_code2.txt', 'folder/sample_code3.txt']

    actual = [x[1] for x in _files_to_bundle(codedeploy)]
    assert set(actual) == set(expected)  # unordered comparison


@pytest.mark.slow
def test_get_packages_to_ignore(temp_folder, cleanup_tempfiles):
    requirements_txt = create_tempfile('boto3\npyhocon\n')
    # typical .ramudaignore file:
    ramuda_ignore = create_tempfile(textwrap.dedent("""\
        boto3*
        botocore*
        python-dateutil*
        six*
        docutils*
        jmespath*
        futures*
    """))
    # schedule the temp_files for cleanup:
    cleanup_tempfiles.extend([requirements_txt, ramuda_ignore])
    _install_dependencies_with_pip(requirements_txt, temp_folder[0])

    packages = os.listdir(temp_folder[0])
    log.info('packages in test folder:')
    for package in packages:
        log.debug(package)

    matches = get_packages_to_ignore(temp_folder[0], ramuda_ignore)
    log.info('matches in test folder:')
    for match in sorted(matches):
        log.debug(match)
    assert 'boto3/__init__.py' in matches
    assert 'pyhocon' not in matches


@pytest.mark.slow
def test_cleanup_folder(temp_folder, cleanup_tempfiles):
    requirements_txt = create_tempfile('boto3\npyhocon\n')
    # typical .ramudaignore file:
    ramuda_ignore = create_tempfile(textwrap.dedent("""\
        boto3*
        botocore*
        python-dateutil*
        six*
        docutils*
        jmespath*
        futures*
    """))
    cleanup_tempfiles.extend([requirements_txt, ramuda_ignore])
    log.info(_install_dependencies_with_pip(
        here('resources/sample_lambda/requirements.txt'), temp_folder[0]))

    log.debug('test folder size: %s' % get_size(temp_folder[0]))
    cleanup_folder(temp_folder[0], ramuda_ignore)
    log.debug('test folder size: %s' % get_size(temp_folder[0]))
    packages = os.listdir(temp_folder[0])
    log.debug(packages)
    assert 'boto3' not in packages
    assert 'pyhocon' in packages


@pytest.mark.slow
def test_install_dependencies_with_pip(temp_folder, cleanup_tempfiles):
    #temp_folder = [mkdtemp()]
    #os.chdir(temp_folder[0])
    #print(temp_folder)

    requirements_txt = create_tempfile('werkzeug\n')
    cleanup_tempfiles.append(requirements_txt)
    log.info(_install_dependencies_with_pip(
        requirements_txt,
        temp_folder[0]))
    packages = os.listdir(temp_folder[0])
    for package in packages:
        log.debug(package)
    assert 'werkzeug' in packages


@pytest.mark.slow
@check_npm_precondition
def test_install_dependencies_with_npm(temp_folder):
    with open('./package.json', 'w') as req:
        req.write(textwrap.dedent("""\
            {
              "name": "my-sample-lambda",
              "version": "0.0.1",
              "description": "A very simple lambda function",
              "main": "index.js",
              "dependencies": {
                "1337": "^1.0.0"
              }
            }"""))

    log.info(_install_dependencies_with_npm())
    packages = os.listdir(os.path.join(temp_folder[0], 'node_modules'))
    for package in packages:
        log.debug(package)
    assert '1337' in packages


# this was a bundle_lambda test in test_ramuda_aws.py before
def test_get_zipped_file(temp_folder):
    folders_from_file = [
        {'source': './vendored', 'target': '.'},
        {'source': './impl', 'target': 'impl'}
    ]
    os.environ['ENV'] = 'DEV'
    os.mkdir('./vendored')
    os.mkdir('./impl')
    with open('./requirements.txt', 'w') as req:
        req.write('pyhocon\n')
    with open('./handler.py', 'w') as req:
        req.write('# this is my lambda handler\n')
    with open('./settings_dev.conf', 'w') as req:
        req.write('\n')
    # write 1MB file -> this gets us a zip file that is within the 50MB limit
    with open('./impl/bigfile', 'wb') as bigfile:
        print(bigfile.name)
        bigfile.write(os.urandom(1000000))  # 1 MB

    zipfile = _get_zipped_file('./handler.py', folders_from_file)

    zipped_size = len(zipfile)
    unzipped_size = get_size('vendored') + get_size('impl') + os.path.getsize(
        'handler.py')
    assert zipped_size < unzipped_size


def test_prebundle(temp_folder):
    log.info('running test_prebundle')

    def _script(name):
        return here('resources/sample_lambda_with_prebundle/%s.sh' % name)

    context = {'tool': 'ramuda', 'command': 'deploy'}
    config = {
        "lambda": {
            "handlerFunction": "handler.handle",
            "handlerFile": "handler.py",
            "description": "Test lambda with prebundle",
            "timeout": 300,
            "memorySize": 128
        },
        "bundling": {
            "preBundle": [
                _script('sample_script')
            ],
            "folders": [
                {
                    "source": "./vendored",
                    "target": "."
                }
            ]
        }
    }

    prebundle((context, {'ramuda': config}))
    assert os.path.isfile('test_ramuda_prebundle.txt')


# this was a bundle_lambda test in test_ramuda_aws.py before
def test_get_zipped_file_exceeds_limit(temp_folder):
    folders_from_file = [
        {'source': './vendored', 'target': '.'},
        {'source': './impl', 'target': 'impl'}
    ]
    os.environ['ENV'] = 'DEV'

    os.mkdir('./vendored')
    os.mkdir('./impl')
    with open('./requirements.txt', 'w') as req:
        req.write('pyhocon\n')
    with open('./handler.py', 'w') as req:
        req.write('# this is my lambda handler\n')
    with open('./settings_dev.conf', 'w') as req:
        req.write('\n')
    # write 51MB file -> this gets us a zip file that exceeds the 50MB limit
    with open('./impl/bigfile', 'wb') as bigfile:
        #print(bigfile.name)
        bigfile.write(os.urandom(51100000))  # 51 MB

    zipfile = _get_zipped_file('./handler.py', folders_from_file)
    assert zipfile is None
    # TODO add proper log capture that works!


def test_get_zipped_file_empty_requirements_txt(temp_folder):
    def list_zip(input_zip):
        # use string as buffer
        input_zip = ZipFile(io.BytesIO(input_zip))
        for name in input_zip.namelist():
            yield name

    folders_from_file = [
        {'source': './impl', 'target': 'impl'}
    ]
    os.environ['ENV'] = 'DEV'
    os.mkdir('./impl')
    # empty requirements.txt file
    with open('./requirements.txt', 'w') as req:
        req.write('\n')
    with open('./handler.py', 'w') as req:
        req.write('# this is my lambda handler\n')
    with open('./settings_dev.conf', 'w') as req:
        req.write('\n')
    # write 1MB file -> this gets us a zip file that is within the 50MB limit
    with open('./impl/bigfile', 'wb') as bigfile:
        bigfile.write(os.urandom(1000000))  # 1 MB

    zipfile = _get_zipped_file('./handler.py', folders_from_file)

    actual_files = list(list_zip(zipfile))

    assert 'impl/bigfile' in actual_files
    assert 'handler.py' in actual_files
    assert 'vendored' not in actual_files
    assert 'requirements.txt' not in actual_files
    print(actual_files)


def test_get_zipped_file_no_requirements_txt(temp_folder):
    def list_zip(input_zip):
        # use string as buffer
        input_zip = ZipFile(io.BytesIO(input_zip))
        for name in input_zip.namelist():
            yield name

    folders_from_file = [
        {'source': './impl', 'target': 'impl'}
    ]
    os.environ['ENV'] = 'DEV'
    os.mkdir('./impl')
    # no requirements.txt file
    with open('./handler.py', 'w') as req:
        req.write('# this is my lambda handler\n')
    with open('./settings_dev.conf', 'w') as req:
        req.write('\n')
    # write 1MB file -> this gets us a zip file that is within the 50MB limit
    with open('./impl/bigfile', 'wb') as bigfile:
        bigfile.write(os.urandom(1000000))  # 1 MB

    zipfile = _get_zipped_file('./handler.py', folders_from_file)

    actual_files = list(list_zip(zipfile))

    assert 'impl/bigfile' in actual_files
    assert 'handler.py' in actual_files
    assert 'vendored' not in actual_files
    assert 'requirements.txt' not in actual_files
    print(actual_files)
