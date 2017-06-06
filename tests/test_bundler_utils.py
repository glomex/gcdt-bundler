# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function
import os
import fnmatch
import logging

from gcdt_bundler.bundler_utils import glob_files, get_path_info
from . import here

ROOT_DIR = here('./resources/static_files')

log = logging.getLogger(__name__)


def test_find_two_files():
    result = list(glob_files(ROOT_DIR, ['a/**']))
    #assert list(result) == [
    #    (ROOT_DIR + '/a/aa.txt', 'a/aa.txt'),
    #    (ROOT_DIR + '/a/ab.txt', 'a/ab.txt')
    #]
    assert (ROOT_DIR + '/a/aa.txt', 'a/aa.txt') in result
    assert (ROOT_DIR + '/a/ab.txt', 'a/ab.txt') in result


def test_default_include():
    result = list(glob_files(ROOT_DIR))
    assert (ROOT_DIR + '/a/aa.txt', 'a/aa.txt') in result
    assert (ROOT_DIR + '/a/ab.txt', 'a/ab.txt') in result
    assert (ROOT_DIR + '/b/ba.txt', 'b/ba.txt') in result
    assert (ROOT_DIR + '/b/bb.txt', 'b/bb.txt') in result


def test_later_include_has_precedence():
    # note: this testcase is not exactly relevant any more since the tag
    # mechanism has been removed
    result = list(glob_files(ROOT_DIR, ['**', 'a/**']))
    assert (ROOT_DIR + '/b/ba.txt', 'b/ba.txt') in result
    assert (ROOT_DIR + '/b/bb.txt', 'b/bb.txt') in result
    assert (ROOT_DIR + '/a/aa.txt', 'a/aa.txt') in result
    assert (ROOT_DIR + '/a/ab.txt', 'a/ab.txt') in result


def test_exclude_file():
    result = glob_files(ROOT_DIR, ['a/**'], ['a/aa.txt'])
    assert list(result) == [
        (ROOT_DIR + '/a/ab.txt', 'a/ab.txt')
    ]


def test_exclude_file_with_gcdtignore():
    result = glob_files(ROOT_DIR, ['a/**'],
                        gcdtignore=['aa.txt'])
    assert list(result) == [
        (ROOT_DIR + '/a/ab.txt', 'a/ab.txt')
    ]


def test_how_crazy_is_it():
    f = '/a/b/c/d.txt'
    p = '/a/**/d.txt'
    assert fnmatch.fnmatchcase(f, p)


def test_get_path_info_relative():
    path = {'source': 'codedeploy', 'target': ''}
    base, ptz, target = get_path_info(path)
    assert base == os.getcwd()
    assert ptz == 'codedeploy'
    assert target == '/'


def test_get_path_info_abs():
    path = {'source': os.getcwd() + '/codedeploy', 'target': ''}
    base, ptz, target = get_path_info(path)
    assert base == os.getcwd()
    assert ptz == 'codedeploy'
    assert target == '/'
