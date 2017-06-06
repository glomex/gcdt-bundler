# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function
import tarfile
import os
import io
import textwrap
import logging
from zipfile import ZipFile

import pytest
from gcdt_testtools.helpers import temp_folder, create_tempfile, get_size, \
    cleanup_tempfiles, list_zip
from gcdt_testtools import helpers

from gcdt_bundler.bundler import bundle_revision, _install_dependencies_with_pip, \
    _install_dependencies_with_npm, _get_zipped_file, prebundle, make_zip_file_bytes, \
    _add_deps_folder, _site_packages_dir_in_venv
from . import here

log = logging.getLogger(__name__)


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


@pytest.mark.slow
@pytest.mark.parametrize('runtime', ['python2.7', 'python3.6'])
def test_install_dependencies_with_pip(runtime, temp_folder, cleanup_tempfiles):
    venv_dir = '%s/.gcdt/venv' % temp_folder[0]
    requirements_txt = create_tempfile('werkzeug\n')
    cleanup_tempfiles.append(requirements_txt)
    log.info(_install_dependencies_with_pip(
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
@pytest.mark.parametrize('runtime', ['nodejs6.10', 'nodejs4.3'])
def test_install_dependencies_with_npm(runtime, temp_folder):
    with open('./package.json', 'w') as req:
        req.write(textwrap.dedent("""\
            {
              "name": "my-sample-lambda",
              "version": "0.0.1",
              "description": "A very simple lambda function",
              "main": "index.js",
              "dependencies": {
                "1337": "^1.0.1"
              }
            }"""))

    log.info(_install_dependencies_with_npm(runtime))
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
    #with open('./settings_dev.conf', 'w') as req:
    #    req.write('\n')
    # write 1MB file -> this gets us a zip file that is within the 50MB limit
    with open('./impl/bigfile', 'wb') as bigfile:
        print(bigfile.name)
        bigfile.write(os.urandom(1000000))  # 1 MB

    gcdtignore = textwrap.dedent("""\
        boto3*
        botocore*
        python-dateutil*
        six*
        docutils*
        jmespath*
        futures*
    """)

    zipfile = _get_zipped_file('./handler.py', folders_from_file,
                               gcdtignore=gcdtignore)

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

    zipfile = _get_zipped_file('./handler.py', folders_from_file,
                               settings=b'some test config')

    actual_files = list(list_zip(zipfile))

    assert 'impl/bigfile' in actual_files
    assert 'handler.py' in actual_files
    assert 'vendored' not in actual_files
    assert 'settings.conf' in actual_files
    assert 'requirements.txt' not in actual_files
    print(actual_files)


def test_get_zipped_file_no_requirements_txt(temp_folder):
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

    zipfile = _get_zipped_file('handler.py', folders_from_file)

    actual_files = list(list_zip(zipfile))

    assert 'impl/bigfile' in actual_files
    assert 'handler.py' in actual_files
    assert 'vendored' not in actual_files
    assert 'requirements.txt' not in actual_files
    print(actual_files)


# using / developing a better gcdt-bundler structure
def test_make_zip_file_bytes(temp_folder):
    file_a = create_tempfile('some content for my file a', dir=temp_folder[0])
    file_b = create_tempfile('some content for my file b', dir=temp_folder[0])
    rel_file_a = file_a[len(temp_folder[0])+1:]
    rel_file_b = file_b[len(temp_folder[0])+1:]

    folders_from_file = [
        {'source': rel_file_a, 'target': 'blub'},
        {'source': rel_file_b, 'target': 'blub'}
    ]

    zipfile = make_zip_file_bytes(folders_from_file)
    actual_files = list(list_zip(zipfile))

    assert len(actual_files) == 2
    assert 'blub/' + rel_file_a in actual_files
    assert 'blub/' + rel_file_b in actual_files


def test_make_zip_file_bytes_gcdtignore(temp_folder):
    gcdtignore = ['*.pyc']
    os.mkdir('./root')
    rootfolder = temp_folder[0] + '/root'
    file_a = create_tempfile('some content for my file a', dir=rootfolder)
    file_b = create_tempfile('some content for my file b', dir=rootfolder)
    file_c = create_tempfile('some content for my file b', dir=rootfolder,
                             suffix='.pyc')  # this one is ignored
    rel_file_a = file_a[len(rootfolder)+1:]
    rel_file_b = file_b[len(rootfolder)+1:]

    folders_from_file = [
        {'source': 'root/**', 'target': 'blub/'}
    ]

    zipfile = make_zip_file_bytes(folders_from_file, gcdtignore=gcdtignore)
    actual_files = list(list_zip(zipfile))

    assert len(actual_files) == 2
    assert 'blub/' + rel_file_a in actual_files
    assert 'blub/' + rel_file_b in actual_files


def test_make_zip_file_bytes_add_handler(temp_folder):
    # handler is added like every other file...
    os.mkdir('./root')
    rootfolder = temp_folder[0] + '/root'
    file_a = create_tempfile('some content for my handler', dir=rootfolder,
                             suffix='.py')
    rel_file_a = file_a[len(rootfolder)+1:]

    folders_from_file = [
        {'source': 'root/' + rel_file_a, 'target': ''}
    ]

    zipfile = make_zip_file_bytes(folders_from_file)
    actual_files = list(list_zip(zipfile))

    assert len(actual_files) == 1
    assert rel_file_a in actual_files


def test_make_zip_file_bytes_add_artifact():
    settings_file = {
        'content': b'this is my settings file content',
        'target': 'settings.conf',
        'attr': 0o644 << 16  # permissions -r-wr--r--
    }
    zipfile = make_zip_file_bytes([], artifacts=[settings_file])
    actual_files = list(list_zip(zipfile))

    assert len(actual_files) == 1
    assert 'settings.conf' in actual_files
