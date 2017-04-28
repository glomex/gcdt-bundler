[![Documentation](https://readthedocs.org/projects/beedo/badge/?version=latest)](http://gcdt.readthedocs.io/en/latest/)
[![License](http://img.shields.io/badge/license-MIT-yellowgreen.svg)](LICENSE) 
[![GitHub issues](https://img.shields.io/github/issues/glomex/glomex-cloud-deployment-tools.svg?maxAge=2592000)](https://github.com/glomex/glomex-cloud-deployment-tools/issues)

# Plugin for gcdt

author: glomex SRE Team
gcdt: https://github.com/glomex/gcdt

Features include:

* bundle artifacts (zip file) for tenkai and ramuda


## Running tests

Please make sure to have good test coverage for your plugin so we can always make sure your plugin runs with the upcoming gcdt version.

Run tests like so:

``` bash
$ python -m pytest -vv --cov-report term-missing tests/test_*
```


## License

Copyright (c) 2017 glomex and others.
gcdt and plugins are released under the MIT License (see LICENSE).
