#!/usr/bin/env python
"""
    Copyright (c) 2020 University of Illinois Board of Trustees
    All rights reserved.

    Developed by:       Technology Services
                       University of Illinois at Urbana-Champaign
                        https://techservices.illinois.edu/

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal with the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

* Redistributions of source code must retain the above copyright
  notice, this list of conditions and the following disclaimers.
* Redistributions in binary form must reproduce the above copyright
  notice, this list of conditions and the following disclaimers in the
  documentation and/or other materials provided with the distribution.
* Neither the names of Technology Services, University of Illinois at
  Urbana-Champaign, nor the names of its contributors may be used to
  endorse or promote products derived from this Software without
  specific prior written permission.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE CONTRIBUTORS OR COPYRIGHT HOLDERS BE LIABLE FOR
ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS WITH THE SOFTWARE.
"""

import argparse
import boto3
from configparser import ConfigParser
from jproperties import Properties
import logging
import os
import re
import shlex

logger = logging.getLogger(__name__)
ssm = boto3.client('ssm')

ENV_STYLES = {'bash', 'dotenv', 'docker'}
ENV_PARAMETER_NAME_RE = re.compile(r'/(?P<name>[a-zA-Z_][a-zA-Z_0-9]*)$')

INI_STYLES = {'ini'}
INI_PARAMETER_NAME_RE = re.compile(r'/(?:(?P<section>[a-zA-Z0-9_-]+)\.)(?P<name>[a-zA-Z0-9_-]+)$')

JAVA_STYLES = {'java'}
JAVA_PARAMETER_NAME_RE = re.compile(r'/(?P<name>.+)$')

def parseArguments():
    parser = argparse.ArgumentParser(description='Walk the path of an SSM Parameter Store and build an environment file from the results.')
    parser.add_argument(
        '--output', '-o',
        action='store',
        metavar='FILE',
        default=os.environ.get('OUTPUT', '/dev/stdout'),
        help='filename to store the environment variables in',
    )
    parser.add_argument(
        '--recursive', '-r',
        action='store_true',
        default=os.environ.get('RECURSIVE', 'False').lower() in ('true', 't', 'yes', 'y', '1'),
        help='recursively walk the parameter store path',
    )
    parser.add_argument(
        '--style', '-s',
        action='store',
        choices=['bash','dotenv','docker', 'ini', 'java'],
        default=os.environ.get('STYLE', 'dotenv'),
        help='what style to output. dotenv and bash both quote for the shell but bash adds "export", and docker is a plain output',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='count',
        default=0,
        help='increase the logging level (app INFO, app DEBUG, all DEBUG)',
    )

    parser.add_argument(
        'parameters',
        action='store',
        nargs='*',
        metavar='ssm-path',
        default=[os.environ[k] for k in sorted(os.environ.keys()) if k.startswith('PARAMETER')],
        help='parameter paths to walk',
    )

    return parser.parse_args()

def generateParameters(path, recursive=False):
    """
    Take a path in SSM Parameter Store, get all of its keys and values, and
    yield them to the calling function.

    This does not throw the errors returned by ``get_parameters_by_path``.
    Instead they are logged and iteration stops.

    Args:
        path: The path in SSM Parameter Store to walk.
        recursive (optional): Whether to walk the ``path`` recursively or not.
            The default is to not recurse.
    """
    if not path:
        raise ValueError('the path is not specified')
    if not path.startswith('/'):
        path = '/' + path

    nextToken = None
    while True:
        logger.info('Getting parameters for %(path)r', { 'path': path })

        reqParams = dict(
            Path=path,
            Recursive=recursive,
            WithDecryption=True,
        )
        if nextToken:
            reqParams['NextToken'] = nextToken
        try:
            response = ssm.get_parameters_by_path(**reqParams)
        except Exception:
            logger.exception('Unable to process parameters for %(path)r', { 'path': path })
            break
        else:
            yield from response.get('Parameters', [])

            nextToken = response.get('NextToken')
            if not nextToken:
                logger.info('Finished iterating parameters')
                break

def processEnvParameters(paths, fh, recursive=False, style='dotenv'):
    """
    Take paths in SSM Parameter Store, get all of their keys and values, and
    write them to the output file handle as shell variables.

    Args:
        paths: The paths in SSM Parameter Store to walk.
        fh: An open, writeable file handle to output the shell key=value.
        recursive (optional): Whether to walk the ``paths`` recursively or not.
            The default is to not recurse.
        style (optional): What style of envvars to output (bash, dotenv, docker).
            The default is to use dotenv.
    """
    for path in paths:
        for param in generateParameters(path, recursive=reecursive):
            if not m := ENV_PARAMETER_NAME_RE.search(param['Name']):
                logger.warning('%(Name)s: skipping parameter because of invalid bash name', param)
                continue
            name = m.group('name')
            if style in {'bash', 'dotenv'}:
                value = shlex.quote(param['Value'])
            else:
                value = param['Value']

            if param['Type'] == 'SecureString':
                logger.debug('%(path)s: %(name)s = ********', {
                    'path': param['Name'],
                    'name': name
                })
            else:
                logger.debug('%(path)s: %(name)s = %(value)s', {
                    'path': param['Name'],
                    'name': name,
                    'value': value
                })

            fh.write(f"# {param['Name']}\n")
            if style == 'bash':
                fh.write('export ')
            fh.write(f"{name}={value}\n")

def processINIParameters(paths, config, recursive=False):
    """
    Take paths in SSM Parameter Store, get all of their keys and values, and
    write them to the output file handle as ini values.

    Args:
        paths: The paths in SSM Parameter Store to walk.
        fh: An open, writeable file handle to output the ini values.
        recursive (optional): Whether to walk the ``paths`` recursively or not.
            The default is to not recurse.
    """
    config = ConfigParser()
    for path in paths:
        for param in generateParameters(path, recursive=reecursive):
            if not m := INI_PARAMETER_NAME_RE.search(param['Name']):
                logger.warning('%(Name)s: skipping parameter because of invalid ini name', param)
                continue
            section = m.group('section') if m.group('section') else 'main'
            name = m.group('name')
            value = param['Value']

            if param['Type'] == 'SecureString':
                logger.debug('%(path)s: %(name)s = ********', {
                    'path': param['Name'],
                    'name': name
                })
            else:
                logger.debug('%(path)s: %(name)s = %(value)s', {
                    'path': param['Name'],
                    'name': name,
                    'value': value
                })

            if not section in config:
                config[section] = {}
            config[section][name] = value

    config.write(fh)

def processJavaParameters(paths, fh, recursive=False):
    """
    Take paths in SSM Parameter Store, get all of their keys and values, and
    write them to the output file handle as Java property values.

    Args:
        paths: The paths in SSM Parameter Store to walk.
        fh: An open, writeable file handle to output the Java properties values.
        recursive (optional): Whether to walk the ``paths`` recursively or not.
            The default is to not recurse.
    """
    props = Properties()
    for path in paths:
        for param in generateParameters(path, recursive=reecursive):
            if not m := JAVA_PARAMETER_NAME_RE.search(param['Name']):
                logger.warning('%(Name)s: skipping parameter because of invalid Java property name', param)
                continue
            name = m.group('name')
            value = param['Value']

            if param['Type'] == 'SecureString':
                logger.debug('%(path)s: %(name)s = ********', {
                    'path': param['Name'],
                    'name': name
                })
            else:
                logger.debug('%(path)s: %(name)s = %(value)s', {
                    'path': param['Name'],
                    'name': name,
                    'value': value
                })

            props[name] = value

    props.store(fh, encoding='utf-8')

if __name__ == '__main__':
    args = parseArguments()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose >= 3 else logging.WARNING,
        format='[%(levelname)s %(asctime)s] (%(name)s) %(message)s',
        handlers=[
            logging.StreamHandler(),
        ]
    )
    if args.verbose == 1:
        logger.setLevel(logging.INFO)
    elif args.verbose == 2:
        logger.setLevel(logging.DEBUG)

    logger.debug('Arg: output = %(value)r', { 'value': args.output })
    logger.debug('Arg: recursive = %(value)r', { 'value': args.recursive })
    logger.debug('Arg: style = %(value)r', { 'value': args.style })

    with open(args.output, 'w') as fh:
        if args.style in ENV_STYLES:
            processEnvParameters(args.parameters, fh, recursive=args.recursive, style=args.style)
        elif args.style in INI_STYLES:
            processINIParameters(args.parameters, fh, recursive=args.recursive)
        elif args.style in JAVA_STYLES:
            processJavaParameters(args.parameters, fh, recursive=args.recursive)