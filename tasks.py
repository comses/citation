from invoke import task
from invoke.tasks import call

COVERAGE_IGNORED_PACKAGES = ('test', 'settings', 'migrations', 'wsgi', 'tasks', 'apps.py')


@task
def clean_update(ctx):
    ctx.run("git fetch --all && git reset --hard origin/master")


@task
def test(ctx, coverage=False):
    coverage_cmd = 'python3'
    if coverage:
        ignored = ['*{0}*'.format(ignored_pkg) for ignored_pkg in COVERAGE_IGNORED_PACKAGES]
        coverage_cmd = "coverage run --source='citation' --omit=" + ','.join(ignored)
    ctx.run('{} run_tests.py'.format(coverage_cmd))


@task(pre=[call(test, coverage=True)])
def coverage(ctx):
    ctx.run('coverage html')
