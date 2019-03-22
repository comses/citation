import logging

from django.core.management.base import BaseCommand
from django.core.cache import caches

from catalog.core.visualization.data_access import build_cache

logger = logging.getLogger(__name__)


memory = caches['default']


class Command(BaseCommand):
    help = '''Build pandas dataframe cache of primary data'''

    def handle(self, *args, **options):
        dfs = build_cache()
        for df_name, df in dfs.items():
            memory.set(df_name, df, None)
            logger.info('cached %s', df_name)
