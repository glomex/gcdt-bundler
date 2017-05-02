# -*- coding: utf-8 -*-
"""A gcdt-plugin which to prepare bundles (zip-files)."""
from __future__ import unicode_literals, print_function
import os
import sys
import shutil
import tarfile
import subprocess
import io
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import warnings
from optparse import Values

import pathspec
from clint.textui import colored
#from pip.baseparser import parser
from pip.baseparser import ConfigOptionParser
import pip.commands.install

from gcdt import gcdt_signals
from gcdt.utils import execute_scripts
from gcdt.gcdt_logging import getLogger


log = getLogger(__name__)


# from tenkai_core:
def bundle_revision(outputpath='/tmp'):
    """Prepare the tarfile for the revision.

    :param outputpath:
    :return: tarfile_name
    """
    tarfile_name = _make_tar_file(path='./codedeploy',
                                  outputpath=outputpath)
    return tarfile_name


def _files_to_bundle(path):
    for root, dirs, files in os.walk(path):
        for f in files:
            full_path = os.path.join(root, f)
            archive_name = full_path[len(path) + len(os.sep):]
            # print "full_path, archive_name" + full_path, archive_name
            yield full_path, archive_name


def _make_tar_file(path, outputpath):
    # make sure we add a unique identifier when we are running within jenkins
    file_suffix = os.getenv('BUILD_TAG', '')
    destfile = '%s/tenkai-bundle%s.tar.gz' % (outputpath, file_suffix)
    with tarfile.open(destfile, 'w:gz') as tar:
        for full_path, archive_name in _files_to_bundle(path=path):
            tar.add(full_path, recursive=False, arcname=archive_name)
    return destfile


# ramuda bundling
def _get_zipped_file(
        handler_filename, folders,
        runtime='python2.7',
        settings=None):
    if runtime == 'python2.7':
        install_failed = \
            _install_dependencies_with_pip('requirements.txt', './vendored')
        if install_failed:
            return
    elif runtime == 'nodejs4.3':
        install_failed = \
            _install_dependencies_with_npm()
        if install_failed:
            return

    zipfile = make_zip_file_bytes(
        handler=handler_filename,
        paths=folders, settings=settings)
    size_limit_exceeded = check_buffer_exceeds_limit(zipfile)
    if size_limit_exceeded:
        return

    return zipfile


# @make_spin(Default, 'Installing dependencies...')
def _install_dependencies_with_pip(requirements_file, destination_folder):
    """installs dependencies from a pip requirements_file to a local
    destination_folder

    :param requirements_file path to valid requirements_file
    :param destination_folder a foldername relative to the current working
    directory
    :return: exit_code
    """
    if not os.path.isfile(requirements_file):
        return 0
    # TODO: definitely subprocess is NOT the best way to call a python tool!
    cmd = ['pip', 'install', '-r', requirements_file, '-t', destination_folder]

    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(
            '\033[01;31mError running command: %s resulted in the ' % e.cmd +
            'following error: \033[01;32m %s' % e.output)
        return 1
    return 0


# version without popen
'''
def _install_dependencies_with_pip(requirements_file, destination_folder):
    i = pip.commands.install.InstallCommand()
    params = ['-r', requirements_file]
    options, args = i.parse_args(params)
    options.venv = destination_folder
    options.venv_base = destination_folder
    options.respect_venv = True
    options.require_venv = True
    options.no_input = True
    options.verbose = 2
    log.debug('PIP parsed options: %s' % options)
    log.debug('PIP parsed args: %s' % args)

    log.debug('PIP exec: %s' % i.run(options, args))
'''

def _install_dependencies_with_npm():
    """installs dependencies from a package.json file

    :return: exit_code
    """
    if not os.path.isfile('package.json'):
        return 0
    cmd = ['npm', 'install']

    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(
            '\033[01;31mError running command: %s resulted in the ' % e.cmd +
            'following error: \033[01;32m %s' % e.output)
        return 1
    return 0


def files_to_zip(path):
    for root, dirs, files in os.walk(path):
        for f in files:
            full_path = os.path.join(root, f)
            archive_name = full_path[len(path) + len(os.sep):]
            # print 'full_path, archive_name' + full_path, archive_name
            yield full_path, archive_name


def make_zip_file_bytes(paths, handler, settings=None):
    """Create the bundle zip file.

    :param paths:
    :param handler:
    :param settings: ramuda config settings entry
    :return: exit_code
    """
    log.debug('creating zip file...')
    buf = io.BytesIO()
    """
    folders = [
        { source = './vendored', target = '.' },
        { source = './impl', target = '.' }
    ]
    as ConfigTree:
    [ConfigTree([('source', './vendored'), ('target', '.')]),
     ConfigTree([('source', './impl'), ('target', './impl')])]
    """
    # automatically add vendored directory
    vendored = {}
    # check if ./vendored folder is contained!
    vendored_missing = True
    for p in paths:
        if p['source'] == './vendored':
            vendored_missing = False
            break
    if vendored_missing:
        # add missing ./vendored folder to paths
        vendored['source'] = './vendored'
        vendored['target'] = '.'
        paths.append(vendored)
    cleanup_folder('./vendored')  # TODO this should be replaced by better glob!
    # TODO: also exclude *.pyc
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with ZipFile(buf, 'w', ZIP_DEFLATED) as z:
            z.debug = 0
            for path in paths:
                path_to_zip = path.get('source')
                target = path.get('target', path_to_zip)
                # print 'path to zip ' + path_to_zip
                # print 'target is ' + target
                for full_path, archive_name in files_to_zip(path=path_to_zip):
                    # print 'full_path ' + full_path
                    archive_target = target + '/' + archive_name
                    # print 'archive target ' + archive_target
                    z.write(full_path, archive_target)

            # add settings file
            # if 'settings' in config and config['settings']:
            if settings:
                # give settings.conf -rw-r--r-- permissions
                # TODO allow json files for non-hocon setups
                settings_file = ZipInfo('settings.conf')
                #settings_file.external_attr = 0644 << 16L # permissions -r-wr--r--
                settings_file.external_attr = 0o644 << 16 # permissions -r-wr--r--
                z.writestr(settings_file, settings)
            z.write(handler, os.path.basename(handler))

    return buf.getvalue()


def check_buffer_exceeds_limit(buf):
    """Check if size is bigger than 50MB.

    :return: True/False returns True if bigger than 50MB.
    """
    buffer_mbytes = float(len(buf) / 1000000.0)
    log.debug('buffer has size %0.2f MB' % buffer_mbytes)
    if buffer_mbytes >= 50.0:
        log.error('Deployment bundles must not be bigger than 50MB')
        log.error('See http://docs.aws.amazon.com/lambda/latest/dg/limits.html')
        return True
    return False


def cleanup_folder(path, ramuda_ignore_file=None):
    # this cleans up the ./vendored (path) folder
    # exclude locally installed gcdt_develop from lambda container
    # print('path: %s' % path)
    matches = get_packages_to_ignore(path, ramuda_ignore_file)
    result_set = set()
    for package in matches:
        split_dir = package.split('/')[0]
        result_set.add(split_dir)
        # print ('added %s to result set' % split_dir)
    for folder in result_set:
        obj = path + '/' + folder
        if os.path.isdir(obj):
            print('deleting directory %s' % obj)
            shutil.rmtree(path + '/' + folder, ignore_errors=False)
        else:
            # print ('deleting file %s') % object
            os.remove(path + '/' + folder)


def get_packages_to_ignore(folder, ramuda_ignore_file):
    if not ramuda_ignore_file:
        ramuda_ignore_file = os.path.expanduser('~') + '/' + '.ramudaignore'
    # we try to read ignore patterns from the standard .ramudaignore file
    # if we can't find one we don't ignore anything
    # from https://pypi.python.org/pypi/pathspec
    try:
        with open(ramuda_ignore_file, 'r') as fh:
            spec = pathspec.PathSpec.from_lines(pathspec.GitIgnorePattern, fh)

        matches = []
        for match in spec.match_tree(folder):
            matches.append(match)
        return matches
    except IOError:
        print(colored.yellow('Warning: ') + 'No such file: %s' %
              ramuda_ignore_file)
        return []
    except Exception as e:
        print(e)
        return []


## signal handlers
def prebundle(params):
    """Trigger legacy pre-bundle hooks.
    :param params: context, config (context - the _awsclient, etc..
                   config - for all tools (kumo, tenkai, ...))
    """
    context, config = params
    tool = context['tool']
    cmd = context['command']
    if tool == 'ramuda' and cmd in ['bundle', 'deploy']:
        cfg = config['ramuda']
        prebundle_scripts = cfg['bundling'].get('preBundle', None)
        if prebundle_scripts:
            prebundle_failed = execute_scripts(prebundle_scripts)
            if prebundle_failed:
                context['error'] = 'Failure during prebundle step.'
                return


def bundle(params):
    """create the bundle.
    :param params: context, config (context - the _awsclient, etc..
                   config - for all tools (kumo, tenkai, ...))
    """
    context, config = params
    tool = context['tool']
    cmd = context['command']

    if tool == 'tenkai' and cmd in ['bundle', 'deploy']:
        context['_bundle_file'] = bundle_revision()
    elif tool == 'ramuda' and cmd in ['bundle', 'deploy']:
        cfg = config['ramuda']
        runtime = cfg['lambda'].get('runtime', 'python2.7')
        handler_filename = cfg['lambda'].get('handlerFile')
        # folders_from_file = config['bundling'].get('folders')
        folders = cfg.get('bundling', []).get('folders', [])
        settings = cfg.get('settings', None)
        context['_zipfile'] = _get_zipped_file(
            handler_filename,
            folders,
            runtime=runtime,
            settings=settings)


def register():
    """Please be very specific about when your plugin needs to run and why.
    E.g. run the sample stuff after at the very beginning of the lifecycle
    """
    gcdt_signals.bundle_pre.connect(prebundle)
    gcdt_signals.bundle_init.connect(bundle)


def deregister():
    gcdt_signals.bundle_pre.disconnect(prebundle)
    gcdt_signals.bundle_init.disconnect(bundle)
