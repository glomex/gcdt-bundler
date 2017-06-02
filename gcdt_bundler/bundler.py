# -*- coding: utf-8 -*-
"""A gcdt-plugin which to prepare bundles (zip-files)."""
from __future__ import unicode_literals, print_function
import os
import tarfile
import subprocess
import io
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import warnings
import shutil

from gcdt import gcdt_signals, GcdtError
from gcdt.utils import execute_scripts
from gcdt.gcdt_logging import getLogger
from gcdt.gcdt_defaults import DEFAULT_CONFIG
import nodeenv

from gcdt_bundler.bundler_utils import glob_files, get_path_info


log = getLogger(__name__)
#nodeenv.logger = getLogger('3rd_party')  # you naughty logger!


class VirtualenvError(GcdtError):
    """
    No credentials could be found
    """
    fmt = 'Unable to use virtualenv during ramuda bundling phase.'


class DependencyInstallationError(GcdtError):
    """
    No credentials could be found
    """
    fmt = 'Unable to install pip dependencies for your AWS Lambda function.'


# tenkai bundling:
def bundle_revision(paths, outputpath=None, gcdtignore=None):
    """Create the bundle tar file.

    :param paths: list of path => {'source': ,'target': } 
    :param outputpath: path to store the temp archive file
    :param gcdtignore: list of path => {'source': ,'target': }
    :return: path of the archive
    """
    # tar file since this archive format can contain more files than zip!
    # make sure we add a unique identifier when we are running within jenkins
    if outputpath is None:
        outputpath = '/tmp'
    file_suffix = os.getenv('BUILD_TAG', '')
    if file_suffix:
        file_suffix = '_%s' % file_suffix
    destfile = '%s/tenkai-bundle%s.tar.gz' % (outputpath, file_suffix)
    with tarfile.open(destfile, 'w:gz') as tar:
        for path in paths:
            base, ptz, target = get_path_info(path)
            for full_path, rel_path in \
                    glob_files(base, includes=[ptz],
                               gcdtignore=gcdtignore):
                #print(full_path)
                archive_target = target + rel_path
                tar.add(full_path, recursive=False, arcname=archive_target)
    return destfile


# ramuda bundling
def _site_packages_dir_in_venv(venv_dir):
    python_dir = os.listdir(os.path.join(venv_dir, 'lib'))[0]
    deps_dir = os.path.join(venv_dir, 'lib', python_dir, 'site-packages')
    return deps_dir


def _add_deps_folder(folders, venv_dir):
    # note: this was 'vendored' folder before
    # this version shamelessly using chalice helpers (/github.com/awslabs/chalice/)
    deps_dir = _site_packages_dir_in_venv(venv_dir)
    assert os.path.isdir(deps_dir)

    # check if deps_dir is contained in folders!
    deps_dir_missing = True
    for folder in folders:
        if folder['source'] == deps_dir:
            deps_dir_missing = False
            break
    if deps_dir_missing:
        # add missing deps_dir to folders
        deps_path = {
            'source': deps_dir,
            'target': ''
        }
        folders.append(deps_path)


def _get_zipped_file(
        handler_filename, folders,
        runtime='python2.7',
        settings=None,
        gcdtignore=None,
        keep=False
    ):

    if runtime.startswith('python'):
        # also from chalice:
        def _has_at_least_one_package(filename):
            if not os.path.isfile(filename):
                return False
            with open(filename, 'r') as f:
                # This is meant to be a best effort attempt.
                # This can return True and still have no packages
                # actually being specified, but those aren't common
                # cases.
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        return True
            return False

        venv_dir = DEFAULT_CONFIG['ramuda']['python_bundle_venv_dir']
        req_filename = 'requirements.txt'
        if _has_at_least_one_package(req_filename):
            _install_dependencies_with_pip('requirements.txt', runtime,
                                           venv_dir, keep)
            _add_deps_folder(folders, venv_dir)
    elif runtime.startswith('nodejs'):
        _install_dependencies_with_npm(runtime, keep)

    # add handler to folders
    folders.append({
        'source': handler_filename,
        'target': ''
    })
    artifacts = []
    if settings:
        artifacts.append({
            'content': settings,
            'target': 'settings.conf',
            'attr': 0o644 << 16  # permissions -r-wr--r--
        })

    zipfile = make_zip_file_bytes(folders, artifacts=artifacts,
                                  gcdtignore=gcdtignore)

    size_limit_exceeded = check_buffer_exceeds_limit(zipfile)
    if size_limit_exceeded:
        return

    return zipfile


def _install_dependencies_with_pip(requirements_file, runtime, venv_dir,
                                   keep=False):
    """installs dependencies from a pip requirements_file to a local
    destination_folder

    :param requirements_file: path to valid requirements_file
    :param runtime: AWS Lambda python runtime version to prepare
    :param venv_dir: a foldername relative to the current working
    directory
    :param keep: keep / cache installed packages
    """
    # this bundler version shamelessly uses chalice (/github.com/awslabs/chalice/)
    def _pip_script_in_venv(venv_dir):
        pip_exe = os.path.join(venv_dir, 'bin', 'pip')
        return pip_exe

    if not os.path.isfile(requirements_file):
        return  # 0

    # prepare virtualenv for pip installation
    if keep is False:
        shutil.rmtree(venv_dir, ignore_errors=True)
    try:
        # in order to intermix gcdt and AWS Lambda venvs and runtimes
        # we install virtualenv via subprocess so we can use the '-p' option
        venv_cmd = ['virtualenv', venv_dir, '-p', runtime]
        subprocess.check_output(venv_cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        log.debug('Running command: %s resulted in the ' % e.cmd)
        log.debug('following error: %s' % e.output)
        raise VirtualenvError()

    try:
        pip_exe = _pip_script_in_venv(venv_dir)
        assert os.path.isfile(pip_exe)
        pip_cmd = [pip_exe, 'install', '-r', requirements_file]
        subprocess.check_output(pip_cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        log.debug('Running command: %s resulted in the ' % e.cmd)
        log.debug('following error: %s' % e.output)
        raise DependencyInstallationError()


def _install_dependencies_with_npm(runtime, keep=False):
    """installs dependencies from a package.json file for the right runtime

    :param runtime: AWS Lambda runtime i.e. nodejs6.10
    :param keep: keep / cache installed packages
    """
    # extract from https://nodejs.org/en/download/releases/
    NODEENV_FOLDER = 'nodeenv'
    VERSION_MAP = {
        'nodejs4.3': '4.3.2',
        'nodejs6.10': '6.10.3'
    }
    if keep is False:
        # cleanup nodeenv and node_modules folders
        shutil.rmtree(NODEENV_FOLDER, ignore_errors=True)
        shutil.rmtree('node_modules', ignore_errors=True)
    node_version = VERSION_MAP[runtime]

    # http://code.activestate.com/recipes/52308-the-simple-but-handy-collector-of-a-bunch-of-named/?in=user-97991
    class Bunch:
        def __init__(self, **kwds):
            self.__dict__.update(kwds)

    opt = Bunch(**{
        'node': node_version, 'force': True, 'prompt': None, 'verbose': False,
        'io': False, 'no_npm_clean': False, 'requirements': '',
        'without_ssl': False, 'with_npm': False, 'profile': False,
        'load_average': None, 'jobs': '2', 'update': False, 'make_path': 'make',
        'npm': 'latest', 'clean_src': False, 'prebuilt': True, 'list': False,
        'quiet': False, 'python_virtualenv': False, 'debug': False,
        'config_file': ['./setup.cfg', '~/.nodeenvrc']
    })
    nodeenv.create_environment(NODEENV_FOLDER, opt)

    if not os.path.isfile('package.json'):
        return
    cmd = ['nodeenv/bin/npm', 'install']

    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        log.debug('Running command: %s resulted in the ' % e.cmd)
        log.debug('following error: %s' % e.output)
        raise DependencyInstallationError()


def make_zip_file_bytes(paths, gcdtignore=None, artifacts=None):
    """Create the bundle zip file. With this version the vendor - folder magic
    has been removed.

    :param paths: list of path => {'source': ,'target': } 
    :param gcdtignore: list of path => {'source': ,'target': }
    :param artifacts: list of artifacts => {'content': ,'target': , 'attr': } 
    :return: exit_code
    """
    if artifacts is None:
        artifacts = []
    log.debug('creating zip file...')
    buf = io.BytesIO()
    """
    paths = [
        { source = './vendored', target = '.' },
        { source = './impl', target = '.' }
    ]
    """
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with ZipFile(buf, 'w', ZIP_DEFLATED) as z:
            z.debug = 0
            for path in paths:
                base, ptz, target = get_path_info(path)
                for full_path, rel_path in \
                        glob_files(base, includes=[ptz],
                                   gcdtignore=gcdtignore):
                    #print('full_path ' + full_path)
                    archive_target = target + rel_path
                    #print('archive target ' + archive_target)
                    z.write(full_path, archive_target)

            # add each artifact as file
            for artifact in artifacts:
                artifact_file = ZipInfo(artifact['target'])
                attr = artifact.get('attr', None)
                if attr:
                    # give artifact -rw-r--r-- permissions
                    artifact_file.external_attr = attr
                z.writestr(artifact_file, artifact['content'])

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
    # TODO: probably better to move the ignore files into our config-readers
    gcdtignore = None
    if os.path.exists('.ramudaignore'):
        with open('~/.ramudaignore', 'r') as ifile:
            gcdtignore = ifile.read()
    if os.path.exists('.gcdtignore'):
        with open('.gcdtignore', 'r') as ifile:
            gcdtignore += ifile.read()

    if tool == 'tenkai' and cmd in ['bundle', 'deploy']:
        cfg = config['tenkai']
        folders = cfg.get('bundling', {}).get('folders', [])
        if len(folders) == 0:
            folders = [{'source': 'codedeploy', 'target': ''}]
        if cmd == 'bundle':
            outputpath = os.getcwd()
        else:
            outputpath = None
        context['_bundle_file'] = \
            bundle_revision(folders, outputpath=outputpath)
    elif tool == 'ramuda' and cmd in ['bundle', 'deploy']:
        cfg = config['ramuda']
        runtime = cfg['lambda'].get('runtime', 'python2.7')
        if runtime not in DEFAULT_CONFIG['ramuda']['runtime']:
            context['error'] = 'Runtime \'%s\' not supported by gcdt.' % runtime
        else:
            handler_filename = cfg['lambda'].get('handlerFile')
            folders = cfg.get('bundling', []).get('folders', [])
            settings = cfg.get('settings', None)
            context['_zipfile'] = _get_zipped_file(
                handler_filename,
                folders,
                runtime=runtime,
                settings=settings,
                gcdtignore=gcdtignore,
                keep=(context['_arguments']['--keep']
                      or DEFAULT_CONFIG['ramuda']['keep'])
            )


def register():
    """Please be very specific about when your plugin needs to run and why.
    E.g. run the sample stuff after at the very beginning of the lifecycle
    """
    gcdt_signals.bundle_pre.connect(prebundle)
    gcdt_signals.bundle_init.connect(bundle)


def deregister():
    gcdt_signals.bundle_pre.disconnect(prebundle)
    gcdt_signals.bundle_init.disconnect(bundle)
