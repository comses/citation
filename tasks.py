from invoke import task
from invoke.tasks import call

import logging

logger = logging.getLogger(__name__)


@task
def clean_update(ctx):
    ctx.run("git fetch --all && git reset --hard origin/master")


@task
def test(ctx, coverage=False):
    coverage_cmd = 'python3'
    if coverage:
        coverage_cmd = "coverage run --source='citation'"
    ctx.run('{} run_tests.py'.format(coverage_cmd))


@task(pre=[call(test, coverage=True)])
def coverage(ctx):
    ctx.run('coverage html')
