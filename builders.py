import textwrap

from buildbot.process import factory
from buildbot.steps.source import Git
from buildbot.steps.shell import Compile, Test, ShellCommand
from buildbot.steps.transfer import FileDownload
from buildbot.steps.python_twisted import Trial

from metabbotcfg.slaves import slaves, get_slaves, names

builders = []

# some slaves just do "simple" builds: get the source, run the tests.  These are mostly
# windows machines where we don't have a lot of flexibility to mess around with virtualenv
def mksimplefactory(test_master=True):
	f = factory.BuildFactory()
	f.addSteps([
	Git(repourl='git://github.com/buildbot/buildbot.git', mode="copy"),
	#FileDownload(mastersrc="bbimport.py", slavedest="bbimport.py", flunkOnFailure=True),
	#ShellCommand(workdir="build/master", env={'PYTHONPATH' : '.;.'}, command=r"python ..\bbimport.py"),
	# use workdir instead of testpath because setuptools sticks its own eggs (including
	# the running version of buildbot) into sys.path *before* PYTHONPATH, but includes
	# "." in sys.path even before the eggs
	Trial(workdir="build/slave", testpath=".",
		env={ 'PYTHON_EGG_CACHE' : '../' },
		tests='buildslave.test',
		usePTY=False,
		name='test slave'),
	])
	if test_master:
		f.addStep(
		Trial(workdir="build/master", testpath=".",
			env={ 'PYTHON_EGG_CACHE' : '../' },
			tests='buildbot.test',
			usePTY=False,
			name='test master'),
		)
	return f

# much like simple buidlers, but it uses virtualenv
def mkfactory(twisted_version='twisted', python_version='python'):
	subs = dict(twisted_version=twisted_version, python_version=python_version)
	f = factory.BuildFactory()
	f.addSteps([
	Git(repourl='git://github.com/buildbot/buildbot.git', mode="copy"),
	FileDownload(mastersrc="virtualenv.py", slavedest="virtualenv.py", flunkOnFailure=True),
	ShellCommand(usePTY=False, command=textwrap.dedent("""
		test -z "$PYTHON" && PYTHON=%(python_version)s;
		SANDBOX=../sandbox-%(python_version)s;
		$PYTHON virtualenv.py --distribute --no-site-packages $SANDBOX || exit 1;
		PATH=$PWD/$SANDBOX/bin:/usr/local/bin:$PATH; 
		PYTHON=$PWD/$SANDBOX/bin/python;
		export PYTHON_EGG_CACHE=$PWD/..;
		# and somehow the install_requires in setup.py doesn't always work:
		$PYTHON -c 'import json' 2>/dev/null || $PYTHON -c 'import simplejson' ||
					$SANDBOX/bin/easy_install simplejson || exit 1;
		$PYTHON -c 'import sqlite3, sys; assert sys.version_info >= (2,6)' 2>/dev/null ||
					$PYTHON -c 'import pysqlite2.dbapi2' ||
					$SANDBOX/bin/easy_install pysqlite || exit 1;
		$SANDBOX/bin/easy_install %(twisted_version)s || exit 1;
		$SANDBOX/bin/easy_install jinja2 || exit 1;
		$SANDBOX/bin/easy_install mock || exit 1;
	""" % subs),
		flunkOnFailure=True,
		haltOnFailure=True,
		name="virtualenv setup"),
	ShellCommand(usePTY=False, command=textwrap.dedent("""
		PYTHON=../sandbox-%(python_version)s/bin/python;
		PATH=../sandbox-%(python_version)s/bin:/usr/local/bin:$PATH; 
		export PYTHON_EGG_CACHE=$PWD/..;
		$PYTHON -c 'import sys; print "Python:", sys.version; import twisted; print "Twisted:", twisted.version'
	""" % subs),
		name="versions"),
	# see note above about workdir vs. testpath
	Trial(workdir="build/slave", testpath='.',
		env={ 'PYTHON_EGG_CACHE' : '../../' },
		tests='buildslave.test',
		trial="../../sandbox-%(python_version)s/bin/trial" % subs,
		usePTY=False,
		name='test slave'),
	Trial(workdir="build/master", testpath='.',
		env={ 'PYTHON_EGG_CACHE' : '../../' },
		tests='buildbot.test',
		trial="../../sandbox-%(python_version)s/bin/trial" % subs,
		usePTY=False,
		name='test master'),
	])
	return f

coverage_factory = factory.BuildFactory()
coverage_factory.addSteps([
	Git(repourl='git://github.com/buildbot/buildbot.git', mode="copy"),
	FileDownload(mastersrc="virtualenv.py", slavedest="virtualenv.py", flunkOnFailure=True),
	ShellCommand(usePTY=False, command=textwrap.dedent("""
		test -z "$PYTHON" && PYTHON=python;
		$PYTHON virtualenv.py --distribute --no-site-packages ../sandbox || exit 1;
		PATH=$PWD/$SANDBOX/bin:/usr/local/bin:$PATH; 
		PYTHON=$PWD/../sandbox/bin/python;
		export PYTHON_EGG_CACHE=$PWD/..;
		# and somehow the install_requires in setup.py doesn't always work:
		$PYTHON -c 'import json' 2>/dev/null || $PYTHON -c 'import simplejson' ||
					../sandbox/bin/easy_install simplejson || exit 1;
		$PYTHON -c 'import sqlite3, sys; assert sys.version_info >= (2,6)' 2>/dev/null || $PYTHON -c 'import pysqlite2.dbapi2' ||
					../sandbox/bin/easy_install pysqlite || exit 1;
		../sandbox/bin/easy_install Twisted || exit 1;
		../sandbox/bin/easy_install jinja2 || exit 1;
		../sandbox/bin/easy_install mock || exit 1;
		../sandbox/bin/easy_install coverage || exit 1;
		(cd master; $PYTHON setup.py develop) || exit 1;
		(cd slave; $PYTHON setup.py develop) || exit 1;
	"""),
		flunkOnFailure=True,
		haltOnFailure=True,
		name="virtualenv setup"),
	ShellCommand(usePTY=False, command=textwrap.dedent("""
		PYTHON=$PWD/../sandbox/bin/python; PATH=../sandbox/bin:/usr/local/bin:$PATH; 
		export PYTHON_EGG_CACHE=$PWD/..;
		../sandbox/bin/coverage run --rcfile=.coveragerc \
			../sandbox/bin/trial buildbot.test buildslave.test \
			|| exit 1;
		../sandbox/bin/coverage html -i --rcfile=.coveragerc \
			-d /home/buildbot/html/buildbot/coverage \
			|| exit 1;
		chmod -R a+rx /home/buildbot/html/buildbot/coverage || exit 1
	"""),
		name='coverage report'),
])


docs_factory = factory.BuildFactory()
docs_factory.addStep(Git(repourl='git://github.com/buildbot/buildbot.git', mode="update"))
docs_factory.addStep(ShellCommand(command="make VERSION=latest docs", name="create docs"))
docs_factory.addStep(ShellCommand(command=textwrap.dedent("""\
		tar -C /home/buildbot/html/buildbot/docs -zvxf master/docs/docs.tgz latest/ &&
		chmod -R a+rx /home/buildbot/html/buildbot/docs/latest
		"""), name="docs to web", flunkOnFailure=True, haltOnFailure=True))
docs_factory.addStep(ShellCommand(command="make VERSION=latest apidocs", name="create apidocs",
			flunkOnFailure=True, haltOnFailure=True))
docs_factory.addStep(ShellCommand(command=textwrap.dedent("""\
		tar -C /home/buildbot/html/buildbot/docs/latest -zxf apidocs/reference.tgz &&
		chmod -R a+rx /home/buildbot/html/buildbot/docs/latest/reference
		"""), name="api docs to web", flunkOnFailure=True, haltOnFailure=True))

#### docs & coverage

builders.append({
	'name' : 'docs',
	'slavenames' : names(get_slaves(buildbot_net=True)),
	'workdir' : 'docs',
	'factory' : docs_factory,
	'category' : 'docs' })

builders.append({
	'name' : 'coverage',
	'slavenames' : names(get_slaves(buildbot_net=True)),
	'workdir' : 'coverage',
	'factory' : coverage_factory,
	'category' : 'docs' })

#### single-slave builders

for sl in get_slaves(run_single=True).values():
	if sl.use_simple:
		f = mksimplefactory(test_master=sl.test_master)
	else:
		f = mkfactory()
	builders.append({
		'name' : 'slave-%s' % sl.slavename,
		'slavenames' : [ sl.slavename ],
		'workdir' : 'slave-%s' % sl.slavename,
		'factory' : f,
		'category' : 'slave' })

#### config builders

twisted_versions = dict(
	tw0810='Twisted==8.1.0',
	tw0820='Twisted==8.2.0',
	tw0900='Twisted==9.0.0',
	tw1000='Twisted==10.0.0',
	tw1010='Twisted==10.1.0',
)

python_versions = dict(
	py24='python2.4',
	py25='python2.5',
	py26='python2.6',
	py27='python2.7',
)

for py, python_version in python_versions.items():
	config_slaves = names(get_slaves(run_config=True, **{py:True}))
	print py, config_slaves
	if not config_slaves:
		continue

	for tw, twisted_version in twisted_versions.items():
		f = mkfactory(twisted_version=twisted_version, python_version=python_version)
		name = "%s-%s" % (py, tw)
		builders.append({
			'name' : name,
			'slavenames' : config_slaves,
			'factory' : f,
			'category' : 'config' })
