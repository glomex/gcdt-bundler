# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function
import os
import sys
import tarfile
import subprocess
import shutil
import zipfile
import tempfile
import time

from gcdt import gcdt_signals, GcdtError
from gcdt.gcdt_logging import getLogger
import pip
import requests
from tqdm import tqdm
from lambda_packages import lambda_packages as lambda_packages_orig

log = getLogger(__name__)
# We lower-case lambda package keys to match lower-cased keys in get_installed_packages()
lambda_packages = {package_name.lower():val for package_name, val in
                   lambda_packages_orig.items()}


class VirtualenvError(GcdtError):
    """
    No credentials could be found
    """
    fmt = 'Unable to use virtualenv during ramuda bundling phase.'


class PipDependencyInstallationError(GcdtError):
    """
    No credentials could be found
    """
    fmt = 'Unable to install pip dependencies for your AWS Lambda function.'


def _site_packages_dir_in_venv(venv_dir):
    python_dir = os.listdir(os.path.join(venv_dir, 'lib'))[0]
    deps_dir = os.path.join(venv_dir, 'lib', python_dir, 'site-packages')
    return deps_dir


# helper functions from Zappa to install precompiled packages
# https://github.com/Miserlou/lambda-packages
def _get_installed_packages(site_packages, site_packages_64):
    """
    Returns a dict of installed packages we care about.
    """
    package_to_keep = []
    if os.path.isdir(site_packages):
        package_to_keep += os.listdir(site_packages)
    if os.path.isdir(site_packages_64):
        package_to_keep += os.listdir(site_packages_64)

    installed_packages = {package.project_name.lower(): package.version for package in
                          pip.get_installed_distributions() if package.project_name in package_to_keep or
                          package.location in [site_packages, site_packages_64]}

    return installed_packages


def _have_correct_lambda_package_version(runtime, package_name, package_version):
    """
    Checks if a given package version binary should be copied over from lambda packages.
    package_name should be lower-cased version of package name.
    """
    lambda_package_details = lambda_packages.get(package_name, {}).get(runtime)

    if lambda_package_details is None:
        return False

    # Binaries can be compiled for different package versions
    # Related: https://github.com/Miserlou/Zappa/issues/800
    if package_version != lambda_package_details['version']:
        return False

    return True


def _extract_lambda_package(runtime, package_name, path):
    """
    Extracts the lambda package into a given path. Assumes the package exists in lambda packages.
    """
    lambda_package = lambda_packages[package_name][runtime]

    # Trash the local version to help with package space saving
    shutil.rmtree(os.path.join(path, package_name), ignore_errors=True)

    tar = tarfile.open(lambda_package['path'], mode="r:gz")
    for member in tar.getmembers():
        tar.extract(member, path)


def _get_manylinux_wheel_url(runtime, package_name, package_version):
    """
    For a given package name, returns a link to the download URL,
    else returns None.
    Related: https://github.com/Miserlou/Zappa/issues/398
    Examples here: https://gist.github.com/perrygeo/9545f94eaddec18a65fd7b56880adbae
    """
    url = 'https://pypi.python.org/pypi/{}/json'.format(package_name)
    try:
        res = requests.get(url, timeout=1.5)
        data = res.json()
        for f in data['releases'][package_version]:
            if f['filename'].endswith(_get_manylinux_wheel_file_suffix(runtime)):
                return f['url']
    except Exception as e: # pragma: no cover
        return None
    return None


def _get_manylinux_wheel_file_suffix(runtime):
    if runtime == 'python2.7':
        return 'cp27mu-manylinux1_x86_64.whl'
    else:
        return 'cp36m-manylinux1_x86_64.whl'


def _download_url_with_progress(url, stream):
    """
    Downloads a given url in chunks and writes to the provided stream (can be any io stream).
    Displays the progress bar for the download.
    """
    resp = requests.get(url, timeout=2, stream=True)
    resp.raw.decode_content = True

    progress = tqdm(unit='B', unit_scale=True, total=int(resp.headers.get('Content-Length', 0)))
    for chunk in resp.iter_content(chunk_size=1024):
        if chunk:
            progress.update(len(chunk))
            stream.write(chunk)

    progress.close()


def _get_cached_manylinux_wheel(runtime, package_name, package_version):
    """
    Gets the locally stored version of a manylinux wheel. If one does not exist, the function downloads it.
    """
    cached_wheels_dir = os.path.join(tempfile.gettempdir(), 'cached_wheels')
    if not os.path.isdir(cached_wheels_dir):
        os.makedirs(cached_wheels_dir)

    wheel_file = '{0!s}-{1!s}-{2!s}'.format(package_name, package_version,
                                            _get_manylinux_wheel_file_suffix(runtime))
    wheel_path = os.path.join(cached_wheels_dir, wheel_file)

    if not os.path.exists(wheel_path):
        # The file is not cached, download it.
        wheel_url = _get_manylinux_wheel_url(runtime, package_name, package_version)
        if not wheel_url:
            return None

        print(" - {}=={}: Downloading".format(package_name, package_version))
        with open(wheel_path, 'wb') as f:
            _download_url_with_progress(wheel_url, f)
    else:
        print(" - {}=={}: Using locally cached manylinux wheel".format(package_name, package_version))

    return wheel_path


def _get_venv_from_python_version():
    return 'python' + str(sys.version_info[0]) + '.' + str(sys.version_info[1])


def _have_any_lambda_package_version(runtime, package_name):
    """
    Checks if a given package has any lambda package version. We can try and use it with a warning.
    package_name should be lower-cased version of package name.
    """
    return lambda_packages.get(package_name, {}).get(runtime) is not None


# our own code to put Zappa code to use
def add_deps_folder(folders, venv_dir):
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


def install_precompiled_packages(venv_dir, runtime):
    """
    Check if we need to replace any of the installed packages with a precompiled
    package.
    
    :param runtime: 
    :return: 
    """
    site_packages = os.path.join(venv_dir, 'lib', _get_venv_from_python_version(), 'site-packages')
    site_packages_64 = os.path.join(venv_dir, 'lib64', _get_venv_from_python_version(), 'site-packages')

    # Then the pre-compiled packages..
    print("Downloading and installing dependencies..")
    installed_packages = _get_installed_packages(site_packages, site_packages_64)
    temp_project_path = os.path.join(tempfile.gettempdir(), str(int(time.time())))

    try:
        for installed_package_name, installed_package_version in installed_packages.items():
            if _have_correct_lambda_package_version(runtime, installed_package_name, installed_package_version):
                print(" - %s==%s: Using precompiled lambda package " % (installed_package_name, installed_package_version,))
                _extract_lambda_package(runtime, installed_package_name, temp_project_path)
            else:
                cached_wheel_path = _get_cached_manylinux_wheel(
                    runtime, installed_package_name, installed_package_version)
                if cached_wheel_path:
                    # Otherwise try to use manylinux packages from PyPi..
                    # Related: https://github.com/Miserlou/Zappa/issues/398
                    shutil.rmtree(os.path.join(temp_project_path, installed_package_name), ignore_errors=True)
                    with zipfile.ZipFile(cached_wheel_path) as zfile:
                        zfile.extractall(temp_project_path)

                elif _have_any_lambda_package_version(
                        runtime, installed_package_name):
                    # Finally see if we may have at least one version of the package in lambda packages
                    # Related: https://github.com/Miserlou/Zappa/issues/855
                    lambda_version = lambda_packages[installed_package_name][runtime]['version']
                    print(" - %s==%s: Warning! Using precompiled lambda package version %s instead!" % (installed_package_name, installed_package_version, lambda_version, ))
                    _extract_lambda_package(runtime, installed_package_name, temp_project_path)

    except Exception as e:
        print(e)
        # XXX - What should we do here?


def install_dependencies_with_pip(requirements_file, runtime, venv_dir,
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
        raise PipDependencyInstallationError()

    install_precompiled_packages(venv_dir, runtime)
