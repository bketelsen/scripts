#!/usr/bin/python

# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import errno
import optparse
import os
import shutil
import subprocess
import sys

from cbuildbot_config import config

_DEFAULT_RETRIES = 3

# Utility functions

def RunCommand(cmd, print_cmd=True, error_ok=False, error_message=None,
               exit_code=False, redirect_stdout=False, redirect_stderr=False,
               cwd=None, input=None):
  # Print out the command before running.
  if print_cmd:
    print >> sys.stderr, "CBUILDBOT -- RunCommand:", ' '.join(cmd)
  if redirect_stdout:
    stdout = subprocess.PIPE
  else:
    stdout = None
  if redirect_stderr:
    stderr = subprocess.PIPE
  else:
    stderr = None
  if input:
    stdin = subprocess.PIPE
  else:
      stdin = None
  proc = subprocess.Popen(cmd, cwd=cwd, stdin=stdin,
                          stdout=stdout, stderr=stderr)
  (output, error) = proc.communicate(input)
  if exit_code:
    return proc.returncode
  if not error_ok and proc.returncode != 0:
    raise Exception('Command "%s" failed.\n' % (' '.join(cmd)) +
                    (error_message or error or output or ''))
  return output

def MakeDir(path, parents=False):
  try:
    os.makedirs(path)
  except OSError, e:
    if e.errno == errno.EEXIST and parents:
      pass
    else:
      raise

def RepoSync(buildroot, rw_checkout, retries=_DEFAULT_RETRIES):
  while retries > 0:
    try:
      RunCommand(['repo', 'sync'], cwd=buildroot)
      if rw_checkout:
        # Always re-run in case of new git repos or repo sync
        # failed in a previous run because of a forced Stop Build.
        RunCommand(['repo', 'forall', '-c', 'git', 'config',
                    'url.ssh://git@gitrw.chromium.org:9222.pushinsteadof',
                    'http://git.chromium.org/git'], cwd=buildroot)
      retries = 0
    except:
      retries -= 1
      if retries > 0:
        print >> sys.stderr, 'CBUILDBOT -- Repo Sync Failed, retrying'
      else:
        print >> sys.stderr, 'CBUILDBOT -- Retries exhausted'
        raise

# Main functions

def _FullCheckout(buildroot, rw_checkout=True, retries=_DEFAULT_RETRIES):
  RunCommand(['sudo', 'rm', '-rf', buildroot])
  MakeDir(buildroot, parents=True)
  RunCommand(['repo', 'init', '-u', 'http://src.chromium.org/git/manifest'],
             cwd=buildroot, input='\n\ny\n')
  RepoSync(buildroot, rw_checkout, retries)

def _IncrementalCheckout(buildroot, rw_checkout=True,
                         retries=_DEFAULT_RETRIES):
  RepoSync(buildroot, rw_checkout, retries)

def _MakeChroot(buildroot):
  cwd = os.path.join(buildroot, 'src', 'scripts')
  RunCommand(['./make_chroot', '--fast'], cwd=cwd)

def _SetupBoard(buildroot, board='x86-generic'):
  cwd = os.path.join(buildroot, 'src', 'scripts')
  RunCommand(['./setup_board', '--fast', '--default', '--board=%s' % board],
             cwd=cwd)

def _Build(buildroot):
  cwd = os.path.join(buildroot, 'src', 'scripts')
  RunCommand(['./build_packages'], cwd=cwd)

def _UprevAllPackages(buildroot):
  cwd = os.path.join(buildroot, 'src', 'scripts')
  RunCommand(['./enter_chroot.sh', '--', './cros_mark_all_as_stable',
              '--tracking_branch="cros/master"'],
             cwd=cwd)

def _UprevPackages(buildroot, revisionfile):
  revisions = None
  if (revisionfile):
    try:
      rev_file = open(revisionfile)
      revisions = rev_file.read()
      rev_file.close()
    except:
      print >> sys.stderr, 'Error reading %s' % revisionfile
      revisions = None

  # Note:  Revisions == "None" indicates a Force Build.
  if revisions and revisions != 'None':
    print 'CBUILDBOT - Revision list found %s' % revisions
    print 'Revision list not yet propagating to build, marking all instead'

  _UprevAllPackages(buildroot)

def _UprevCleanup(buildroot):
  cwd = os.path.join(buildroot, 'src', 'scripts')
  RunCommand(['./cros_mark_as_stable', '--srcroot=..',
              '--tracking_branch="cros/master"', 'clean'],
             cwd=cwd)

def _UprevPush(buildroot):
  cwd = os.path.join(buildroot, 'src', 'scripts')
  RunCommand(['./cros_mark_as_stable', '--srcroot=..',
              '--tracking_branch="cros/master"',
              '--push_options', '--bypass-hooks -f', 'push'],
             cwd=cwd)

def _GetConfig(config_name):
  default = config['default']
  buildconfig = {}
  if config.has_key(config_name):
    buildconfig = config[config_name]
  for key in default.iterkeys():
    if not buildconfig.has_key(key):
      buildconfig[key] = default[key]
  return buildconfig

def main():
  # Parse options
  usage = "usage: %prog [options] cbuildbot_config"
  parser = optparse.OptionParser(usage=usage)
  parser.add_option('-r', '--buildroot',
                    help='root directory where build occurs', default=".")
  parser.add_option('-n', '--buildnumber',
                    help='build number', type='int', default=0)
  parser.add_option('-f', '--revisionfile',
                    help='file where new revisions are stored')
  parser.add_option('--noclobber', action='store_false', dest='clobber',
                    default=True,
                    help='Disables clobbering the buildroot on failure')
  (options, args) = parser.parse_args()

  buildroot = options.buildroot
  revisionfile = options.revisionfile
  clobber = options.clobber

  if len(args) == 1:
    buildconfig = _GetConfig(args[0])
  else:
    print >> sys.stderr, "Missing configuration description"
    parser.print_usage()
    sys.exit(1)
  try:
    if not os.path.isdir(buildroot):
      _FullCheckout(buildroot)
    else:
      _IncrementalCheckout(buildroot)
    chroot_path = os.path.join(buildroot, 'chroot')
    if not os.path.isdir(chroot_path):
      _MakeChroot(buildroot)
    boardpath = os.path.join(chroot_path, 'build', buildconfig['board'])
    if not os.path.isdir(boardpath):
      _SetupBoard(buildroot, board=buildconfig['board'])
    if buildconfig['uprev']:
      _UprevPackages(buildroot, revisionfile)
    _Build(buildroot)
    if buildconfig['uprev']:
      _UprevPush(buildroot)
      _UprevCleanup(buildroot)
  except:
    # something went wrong, cleanup (being paranoid) for next build
    if clobber:
      RunCommand(['sudo', 'rm', '-rf', buildroot], print_cmd=False)
    raise

if __name__ == '__main__':
    main()