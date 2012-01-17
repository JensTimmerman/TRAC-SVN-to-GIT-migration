#!/usr/bin/env python

# trac-pre-receive-hook
# ----------------------------------------------------------------------------
# Copyright (c) 2004 Stephen Hansen
# Copyright (c) 2009 Sebastian Noack
# Copyright (c) 2012 Jens Timmerman
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
# ----------------------------------------------------------------------------

# This git pre-receive hook script is meant to interface to the
# Trac (http://www.edgewall.com/products/trac/) issue tracking/wiki/etc
# system. trac-pre-receive-hook 
#
# It can be used in-place as pre-receive hook. You only have to fill the
# constants defined just below the imports.
#
# It searches commit messages for text in the form of:
#   command #1
#   command #1, #2
#   command #1 & #2
#   command #1 and #2
#
# Instead of the short-hand syntax "#1", "ticket:1" can be used as well, e.g.:
#   command ticket:1
#   command ticket:1, ticket:2
#   command ticket:1 & ticket:2
#   command ticket:1 and ticket:2
#
# In addition, the ':' character can be omitted and issue or bug can be used
# instead of ticket.
#
# You can have more than one command in a message. The following commands
# are supported. There is more than one spelling for each command, to make
# this as user-friendly as possible.
#
#   close, closed, closes, fix, fixed, fixes
#     The specified issue numbers are closed with the contents of this
#     commit message being added to it.
#   references, refs, addresses, re, see
#     The specified issue numbers are left in their current status, but
#     the contents of this commit message are added to their notes.
#
# A fairly complicated example of what you can do is with a commit message
# of:
#
#    Changed blah and foo to do this or that. Fixes #10 and #12, and refs #12.
#
#This pre receive hook will exit with a non zero exit code if a commit message 
#with an unknown action, or without any action, or without any ticket number 
#was detected in the pushed refs.
#
#This can be used to force the usage of commands and ticket numbers in git
#pushes.
#
#To make things more user friendly a pre-commit hook like this can be isntalled
#in each users local repository:
#	#!/bin/sh
#	#
#	# This script checks if a ticket number is present in the commitmessage.
#	if ! egrep 'refs #[0-9]+|closes #[0-9]+' "$1" > /dev/null
#	then
#	        echo "" 1>&2
#	        echo "*** Your commit has been blocked because you give an invalid commit comment." 1>&2
#	        echo "Please make your commit comment contains 'refs' or 'closes' followed by a #ticketnumber." 1>&2
#	        exit 1
#	fi
#
# to fix commit messages disalowed by this hook:
# git rebase -i <failing hash>~1
# change 'pick' to 'r' for the message you want to change
# save and quit
# change the commit message
# save and quit
# try to push again
# 
# you can change multiple commit messages in one go: use <failing-hash>~<number of commits to go back in time>, 
# use 'r' for all of them
# use rebase --continue after fixing problems
# see http://blog.jacius.info/2008/6/22/git-tip-fix-a-mistake-in-a-previous-commit/
#

import sys
import os
import re
from subprocess import Popen, PIPE

TRAC_ENV = '/home/dev/trac/core'
GIT_PATH = '/usr/bin/git'
BRANCHES = ['master']
COMMANDS = {
		'close':      	intern('close'),
            	'closed':     	intern('close'),
            	'closes':     	intern('close'),
            	'fix':        	intern('close'),
            	'fixed':      	intern('close'),
            	'fixes':      	intern('close'),
           	'addresses':  	intern('refs'),
           	're':         	intern('refs'),
           	'references': 	intern('refs'),
           	'refs':       	intern('refs'),
           	'see':        	intern('refs'),
		}

ACCEPTED_STATUSSES = ['accepted','assigned']


# Use the egg cache of the environment if not other python egg cache is given.
if not 'PYTHON_EGG_CACHE' in os.environ:
    os.environ['PYTHON_EGG_CACHE'] = '/tmp/.egg-cache'

# Construct and compile regular expressions for finding ticket references and
# actions in commit messages.
ticket_prefix = '(?:#|(?:ticket|issue|bug)[: ]?)'
ticket_reference = ticket_prefix + '[0-9]+'
ticket_command =  (r'(?P<action>[A-Za-z]*).?'
                   '(?P<ticket>%s(?:(?:[, &]*|[ ]?and[ ]?)%s)*)' %
                   (ticket_reference, ticket_reference))
command_re = re.compile(ticket_command)
ticket_re = re.compile(ticket_prefix + '([0-9]+)')

def call_git(command, args):
    return Popen([GIT_PATH, command] + args, stdout=PIPE).communicate()[0]

def handle_commit(commit, env):
    from trac.ticket import Ticket
    from trac.ticket.web_ui import TicketModule
    from trac.util.text import to_unicode
    from trac.util.datefmt import utc

    msg = to_unicode(call_git('rev-list', ['-n', '1', commit, '--pretty=medium']).rstrip())
    eml = to_unicode(call_git('rev-list', ['-n', '1', commit, '--pretty=format:%ae']).splitlines()[1])

    tickets = {}
    comtkts = command_re.findall(msg.split('\n\n', 1)[1])
    if not comtkts:
         print "no 'refs' or 'closes' in commitmessage for commit %s, aborting push" % commit
	 sys.exit(1)
    for cmd, tkts in comtkts:
        action = COMMANDS.get(cmd.lower())
        if action:
            for tkt_id in ticket_re.findall(tkts):
                tickets.setdefault(tkt_id, []).append(action)
	else: #no action specified, bad commit message!
	    print "no 'refs' or 'closes' in commitmessage for commit %s, aborting push" % commit
	    sys.exit(1)
	
    for tkt_id, actions in tickets.iteritems():
        try:
            db = env.get_db_cnx()
            ticket = Ticket(env, int(tkt_id), db)
	    if not ticket['status'] in ACCEPTED_STATUSSES:
		print "commiting to non-open ticket in commit %s, aborting push" % commit
		sys.exit(2)

        except Exception, e:
            print 'Unexpected error while processing commit %s :' % commit
	    print 'ticket ID %s: %s' % (tkt_id, e)
	    sys.exit(3)

def handle_ref(old, new, ref, env):
    # If something else than the master branch (or whatever is contained by the
    # constant BRANCHES) was pushed, skip this ref.
    if not ref.startswith('refs/heads/') or ref[11:] not in BRANCHES:
        return

    # Get the list of hashs for commits in the changeset.
    args = (old == '0' * 40) and [new] or [new, '^' + old]
    pending_commits = call_git('rev-list', args).splitlines()

    for commit in pending_commits:
        try:
             handle_commit(commit, env)
        except Exception, e:
             print  'Unexpected error while processing commit %s: %s' % (commit[:7], e)
             sys.exit(4)

if __name__ == '__main__':
    from trac.env import open_environment
    env = open_environment(TRAC_ENV)

    for line in sys.stdin:
        handle_ref(env=env, *line.split())
