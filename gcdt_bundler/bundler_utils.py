# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function
import os

import pathspec
from pathlib2 import PurePath, Path

from gcdt.gcdt_logging import getLogger


log = getLogger(__name__)

# based on: https://github.com/finklabs/botodeploy/blob/master/botodeploy/utils_static.py


def glob_files(root_dir, includes=None, excludes=None, gcdtignore=None):
    """Powerful and flexible utility to search and tag files using patterns.
    :param root_dir: directory where we start the search
    :param includes: list or iterator of include pattern tuples (pattern, tag)
    :param excludes: list or iterator of exclude patterns
    :param gcdtignore: list of ignore patterns (gitwildcard format)
    :return: iterator of (absolute_path, relative_path)
    """
    # docu here: https://docs.python.org/3/library/pathlib.html
    if not includes:
        includes = ['**']
    else:
        # we need to iterate multiple times (iterator safeguard)
        includes = list(includes)

    if excludes:
        # we need to iterate multiple times (iterator safeguard)
        excludes = list(excludes)

    if gcdtignore:
        spec = pathspec.PathSpec.from_lines('gitwildmatch', gcdtignore)
        log.debug('gcdtignore patterns: %s', gcdtignore)

    while includes:
        pattern = includes.pop(0)
        # for compatibility with std. python Lib/glop.py:
        # >>>If recursive is true, the pattern '**' will match any files and
        #    zero or more directories and subdirectories.<<<
        if pattern.endswith('**'):
            pattern += '/*'
        matches = list(Path(root_dir).glob(pattern))

        for m in matches:
            if m.is_dir():
                continue

            # some discussion on how to convert a pattern into regex:
            # http://stackoverflow.com/questions/27726545/python-glob-but-against-a-list-of-strings-rather-than-the-filesystem
            pp = PurePath(m)

            # check if m is contained in remaining include patterns
            # (last one wins)
            if includes and any(map(lambda p: pp.match(p), includes)):
                continue

            # check if m is contained in exclude pattern
            if excludes and any(map(lambda p: pp.match(p), excludes)):
                continue

            # check if m is contained in gcdtignore
            if gcdtignore and spec.match_file(str(m)):
                log.debug('Skipped file \'%s\' due to gcdtignore pattern',
                          str(m.relative_to(root_dir)))
                continue

            yield (str(m), str(m.relative_to(root_dir)))


def get_path_info(path):
    # helper to get (base, rel_path, target)
    # path is full path!

    path_to_zip = path.get('source')
    if not os.path.isabs(path_to_zip):
        # transform relative to absolute path if necessary
        path_to_zip = os.path.join(os.getcwd(), path_to_zip)

    # keep folder configs backwards compatible (we did not use glob before)
    if os.path.isdir(path_to_zip):
        # turn folder into glob
        if not path_to_zip.endswith('/'):
            path_to_zip += '/'
        path_to_zip += '**'

    # extract base!!
    s = path_to_zip.rsplit('/', 1)
    base = s[0]
    ptz = s[1]

    target = path.get('target', ptz)
    if not target.endswith('/'):
        target += '/'

    return base, ptz, target
