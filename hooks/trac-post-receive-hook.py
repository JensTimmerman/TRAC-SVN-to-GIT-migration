#!/usr/bin/env python

# trac-post-commit-hook
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

# This git post-receive hook script is meant to interface to the
# Trac (http://www.edgewall.com/products/trac/) issue tracking/wiki/etc
# system. It is based on the Subversion post-commit hook, part of Trac 0.11.
#
# It can be used in-place as post-recevie hook. You only have to fill the
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
#   worked [0-9.]+h
#     The specified amount of hours get added to the ticket. When more then
#     one ticket specified, the hours are equally distributed across the ticket.
#
# A fairly complicated example of what you can do is with a commit message
# of:
#
#    Changed blah and foo to do this or that. Fixes #10 and #12, and refs #12. worked 10.2h

import sys
import os
import re
from subprocess import Popen, PIPE
from datetime import datetime
from operator import itemgetter
import trac
import time

TRAC_ENV = '/home/jens/tractest/'
GIT_PATH = '/usr/bin/git'
BRANCHES = ['master']
COMMANDS = {'close':      intern('close'),
            'closed':     intern('close'),
            'closes':     intern('close'),
            'fix':        intern('close'),
            'fixed':      intern('close'),
            'fixes':      intern('close'),
            'addresses':  intern('refs'),
            're':         intern('refs'),
            'references': intern('refs'),
            'refs':       intern('refs'),
            'see':        intern('refs')}

ADD_HOURS = False

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
hours_re = re.compile("worked\s*(?P<hours>[0-9.]+)h")


def call_git(command, args):

    return Popen([GIT_PATH, command] + args, stdout=PIPE).communicate()[0]


#found in http://trac-hacks.org/browser/timingandestimationplugin/branches/trac0.11/timingandestimationplugin/ticket_daemon.py
def convertfloat(x):
	"some european countries use , as the decimal separator"
 	x = str(x).strip()
	#print "converting: %s" % x
 	if len(x) > 0:
 	    return float(x.replace(',','.'))
 	else:
 	    return 0.0

def readTicketValue(name, tipe, ticket, env,default=0):
    if ticket.values.has_key(name):
        return tipe(ticket.values[name] or default)
    else:
        cursor = env.get_db_cnx().cursor()
 	cursor.execute("SELECT * FROM ticket_custom where ticket=%s and name=%s" , (ticket.id, name))
 	val = cursor.fetchone()
 	if val:
 	    return tipe(val[2] or default)
 	return default


try:
    import trac.util.datefmt
    to_timestamp = trac.util.datefmt.to_timestamp
except Exception:
    to_timestamp = identity


def save_custom_field_value( db, ticket_id, field, value ):
    cursor = db.cursor();
    cursor.execute("SELECT * FROM ticket_custom "
                   "WHERE ticket=%s and name=%s", (ticket_id, field))
    if cursor.fetchone():
        cursor.execute("UPDATE ticket_custom SET value=%s "
                       "WHERE ticket=%s AND name=%s",
                       (value, ticket_id, field))
    else:
        cursor.execute("INSERT INTO ticket_custom (ticket,name, "
                       "value) VALUES(%s,%s,%s)",
                       (ticket_id, field, value))
    db.commit()

DONTUPDATE = "DONTUPDATE"

def save_ticket_change( db, ticket_id, author, change_time, field, oldvalue, newvalue, dontinsert=False):
    """tries to save a ticket change,

       dontinsert means do not add the change if it didnt already exist
    """
    if isinstance(change_time,datetime):
        change_time = to_timestamp(change_time)
    #print "change_time: %s" % change_time
    cursor = db.cursor();
    sql = """SELECT * FROM ticket_change
             WHERE ticket=%s and author=%s and time=%s and field=%s"""

    cursor.execute(sql, (ticket_id, author, change_time, field))
    if cursor.fetchone():
        if oldvalue == DONTUPDATE:
            cursor.execute("""UPDATE ticket_change  SET  newvalue=%s
                       WHERE ticket=%s and author=%s and time=%s and field=%s""",
                           ( newvalue, ticket_id, author, change_time, field))

        else:
            cursor.execute("""UPDATE ticket_change  SET oldvalue=%s, newvalue=%s
                       WHERE ticket=%s and author=%s and time=%s and field=%s""",
                           (oldvalue, newvalue, ticket_id, author, change_time, field))
    else:
        if oldvalue == DONTUPDATE:
            oldvalue = '0'
        if not dontinsert:
            cursor.execute("""INSERT INTO ticket_change  (ticket,time,author,field, oldvalue, newvalue)
                        VALUES(%s, %s, %s, %s, %s, %s)""",
                           (ticket_id, change_time, author, field, oldvalue, newvalue))
    db.commit()

# end found

def handle_commit(commit, env):
    from trac.ticket.notification import TicketNotifyEmail
    from trac.ticket import Ticket
    from trac.ticket.web_ui import TicketModule
    from trac.util.text import to_unicode
    from trac.util.datefmt import utc

    msg = to_unicode(call_git('rev-list', ['-n', '1', commit, '--pretty=medium']).rstrip())
    eml = to_unicode(call_git('rev-list', ['-n', '1', commit, '--pretty=format:%ae']).splitlines()[1])
    now = datetime.now(utc)
    content = msg.split('\n\n', 1)[1]

    tickets = {}
    for cmd, tkts in command_re.findall(content):
        action = COMMANDS.get(cmd.lower())
	#print "action: %s " % action
        if action:
            for tkt_id in ticket_re.findall(tkts):
                tickets.setdefault(tkt_id, []).append(action)

    for tkt_id, actions in tickets.iteritems():
        try:
            db = env.get_db_cnx()
            ticket = Ticket(env, int(tkt_id), db)
	    #print "ticket: %s" % ticket
    	    if ADD_HOURS:
 		#print "message: %s" % content
		hours = hours_re.findall(content)
		if hours:
			#ADD hours to ticket
			hours =  float(hours[0])/len(tickets)
			#code from http://trac-hacks.org/browser/timingandestimationplugin/branches/trac0.11/timingandestimationplugin/ticket_daemon.py
			#print "hours: %s" % hours
			totalHours = readTicketValue("totalhours", convertfloat,ticket,env)
			#print "totalhours: %s" % totalHours
			newtotal = str(totalHours+hours)
			#print "newtotal: %s" % newtotal
			cl = ticket.get_changelog()
			if cl:
				#print "cl: %s" % cl
				most_recent_change = cl[-1]
				change_time  = most_recent_change[0]
				#print "changetime: %s" % change_time
				author = most_recent_change[1]
			else:
				change_time = ticket.time_created
				author = ticket.values["reporter"]
			db =  env.get_db_cnx()
			#print "saving changes"
			save_ticket_change( db, tkt_id, author, change_time, "hours", '0.0', str(hours) )
			save_ticket_change( db, tkt_id, author, change_time, "totalhours", str(totalHours), str(newtotal))
			save_custom_field_value( db, tkt_id, "hours", '0')	
			save_custom_field_value( db, tkt_id, "totalhours", str(newtotal) )
			#print "hour changes saved"

            if 'close' in actions:
                ticket['status'] = 'closed'
                ticket['resolution'] = 'fixed'
	
            # determine sequence number...
            cnum = 0
            tm = TicketModule(env)
            for change in tm.grouped_changelog_entries(ticket, db):
                if change['permanent']:
                    cnum += 1

            ticket.save_changes(eml, msg, now, db, cnum + 1)
            db.commit()

            tn = TicketNotifyEmail(env)
            tn.notify(ticket, newticket=0, modtime=now)
            
            #dirty workaround for being able to save only one ticket/second, should be fixed in track 0.12 (1 ticket/microsecond)
            #see also http://trac.edgewall.org/ticket/9993
            time.sleep(1)
            now = datetime.now(utc)

        except Exception, e:
            print 'Unexpected error while processing commit %s, for ticket ID %s: %s %s' % (commit, tkt_id, e.__class__,e)

def handle_ref(old, new, ref, env):
    # If something else than the master branch (or whatever is contained by the
    # constant BRANCHES) was pushed, skip this ref.
    if not ref.startswith('refs/heads/') or ref[11:] not in BRANCHES:
        return

    # Get the list of hashs for commits in the changeset.
    args = (old == '0' * 40) and [new] or [new, '^' + old]
    pending_commits = call_git('rev-list', args).splitlines()

    # Get the subset of pending commits that are laready seen.
    db = env.get_db_cnx()
    cursor = db.cursor()

    try:
        cursor.execute('SELECT sha1 FROM git_seen WHERE sha1 IN (%s)'
            % ', '.join(['%s'] * len(pending_commits)), pending_commits)
        seen_commits = map(itemgetter(0), cursor.fetchall())
    except db.OperationalError:
        # almost definitely due to git_seen missing
        cursor = db.cursor() # in case it was closed
        cursor.execute('CREATE TABLE git_seen (sha1 TEXT)')
        seen_commits = []

    for commit in pending_commits:
        # If the commit was seen yet, we must skip it.
        if commit in seen_commits:
             continue

        # Remember that have seen this commit, so each commit is only processed once.
        try:
             cursor.execute('INSERT INTO git_seen (sha1) VALUES (%s)', [commit])
        except db.IntegrityError:
             # If an integrity error occurs (e.g. because of an other process has
             # seen the script in the meantime), skip it too.
             continue

        try:
             handle_commit(commit, env)
        except Exception, e:
             print 'Unexpected error while processing commit %s: %s' % (commit[:7], e)
             db.rollback()
        else:
             db.commit()

if __name__ == '__main__':
    from trac.env import open_environment
    env = open_environment(TRAC_ENV)

    for line in sys.stdin:
        handle_ref(env=env, *line.split())

