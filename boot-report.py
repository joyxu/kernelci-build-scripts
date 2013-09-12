#!/usr/bin/env python

import os, sys, subprocess, glob
import tempfile, getopt
import util

mail_to = None

def usage():
    print "Usage: %s [-m <email address>] <base>" %(sys.argv[0])

try:
    opts, args = getopt.getopt(sys.argv[1:], "m:")
except getopt.GetoptError as err:
    print str(err)
    usage()
    sys.exit(1)

for o, a in opts:
    if o == '-m':
        mail_to = a

dir = args[0]
base = os.path.dirname(dir)

if base == '.' or base == '':
    base = os.getcwd()

if not os.path.exists(dir):
    print "ERROR: %s does not exist" %dir

builds = {}
total_fail_count = 0
total_pass_count = 0
for build in os.listdir(dir):
    boards = {}
    build_fail_count = 0
    build_pass_count = 0
    path = os.path.join(dir, build)
    for logfile in glob.glob('%s/boot-*.log' %path):
        (log_prefix, suffix) = os.path.splitext(logfile) 
        board = os.path.basename(log_prefix)[5:] # drop 'boot-'

        result = 'DEAD'
        r = subprocess.check_output('tail -4 %s | grep Result: | cat' %logfile,
                                    shell=True)
        if r:
            result = r.split(':')[-1].strip()

        if result == 'PASS':
            build_pass_count += 1
            total_pass_count += 1
        else:
            build_fail_count += 1
            total_fail_count += 1

        time = 0
        l = subprocess.check_output('tail -4 %s | grep Time: | cat' %logfile,
                                    shell=True)
        if l:
            t = l.split(':')[2]
            try:
                time = float(t.split()[0].strip())
            except ValueError:
                time = -1

        boards[board] = (result, time, logfile)

    if len(boards) > 0:
        builds[build] = (boards, build_fail_count, build_pass_count)

# Don't send mail if there were no builds
if len(builds) == 0:
    print "WARNING: No boot logs found, Giving up."
    sys.exit(1)

# Extract tree/branch from report header
(tree_branch, describe, commit) = util.get_header_info(base)

# Unbuffer stdout so 'print' and subprocess output intermingle correctly
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

#
#  Log to a file as well as stdout (for sending with msmtp)
#
maillog = tempfile.mktemp(suffix='.log', prefix='boot-report')
mail_headers = """From: Kevin Hilman build bot <khilman+build@linaro.org>
To: %s
Subject: %s boot: %d pass, %d fail (%s)

Automated DT boot report for various ARM defconfigs.  

Boot test simply checks if kernel can boot to initramfs with busybox
and run some basic commands (e.g. 'cat /proc/cpuinfo').

""" %(mail_to, tree_branch, total_pass_count, total_fail_count, describe)
if mail_to and maillog:
    stdout_save = sys.stdout
    tee = subprocess.Popen(["tee", "%s" %maillog], stdin=subprocess.PIPE)
    os.dup2(tee.stdin.fileno(), sys.stdout.fileno())
    os.dup2(tee.stdin.fileno(), sys.stderr.fileno())
    print mail_headers

print 'Tree/Branch:', tree_branch
print 'Git describe:', describe
print 'Commit:', commit

# Failure summary
if total_fail_count:
    msg =  "Failed boot tests (console logs at the end)"
    print msg
    print '=' * len(msg)
    for build in builds:
        boards = builds[build][0]
        fail_count = builds[build][1]
        if not fail_count:
            continue
        for board in boards:
            report = boards[board]
            result = report[0]
            if result != 'FAIL':
                continue
            print '%28s: %8s:    %s' %(board, result, build)
    print

# Passing Summary
if total_pass_count:
    msg = "Full Report"
    print msg
    print '=' * len(msg)
    for build in builds:
        boards = builds[build][0]
        print
        print build
        print '-' * len(build)
        for board in boards:
            report = boards[board]
            result = report[0]
            time = report[1]
            logfile = report[2]
            print "%28s %8s:    %d min %4.1f sec" \
                %(board, result, time / 60, time % 60)


sep = "=" * 79

if total_fail_count:
    msg = "Console logs for failures"
    print
    print msg
    print '=' * len(msg)
    print

# Details for failures
for build in builds:
    boards = builds[build][0]
    fail_count = builds[build][1]
    if not fail_count:
        continue

    print build
    print '-' * len(build)
    for board in boards:
        report = boards[board]
        result = report[0]
        if result == 'PASS':
            continue

        n = 24
        line = '%s: %s: last %d lines of boot log:' %(board, result, n)
        print
        print '\t', line
        print '\t' + '-' * len(line)
        print
        logfile = report[2]
        cmd = "cat %s | tr -d '\r' | tail -n%d"  %(logfile, n)
        subprocess.call(cmd, shell=True)
        print

        
print

# Mail the final report
if maillog and mail_to:
    sys.stdout.flush()
    sys.stdout = stdout_save
    subprocess.check_output('cat %s | msmtp --read-envelope-from -t --' %maillog, shell=True)
    if os.path.exists(maillog):
        os.remove(maillog)
    else:
        print "WARNING: mail log %s doesn't exist!" %maillog