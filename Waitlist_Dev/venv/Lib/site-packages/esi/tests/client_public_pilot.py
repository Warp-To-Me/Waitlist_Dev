# flake8: noqa
"""script for testing client with live requests to ESI

Run this script directly. Make sure to also set the environment variable
DJANGO_PROJECT_PATH and DJANGO_SETTINGS_MODULE to match your setup:

You can see the result in your main log file of your Django installation.

Example:
export DJANGO_PROJECT_PATH="/home/erik997/dev/python/django-dev/mysite"
export DJANGO_SETTINGS_MODULE="mysite.settings"

"""

# start django project
import os
import sys

if not 'DJANGO_PROJECT_PATH' in os.environ:
    print('DJANGO_PROJECT_PATH is not set')
    exit(1)

if not 'DJANGO_SETTINGS_MODULE' in os.environ:
    print('DJANGO_SETTINGS_MODULE is not set')
    exit(1)

sys.path.insert(0, os.environ['DJANGO_PROJECT_PATH'])
import django
django.setup()

# normal imports
import concurrent.futures
import logging

from django.core.cache import cache
from esi.clients import EsiClientProvider

cache.clear()
esi = EsiClientProvider()

logger = logging.getLogger('__name__')
logger.level = logging.DEBUG


def main():
    # esi.client.Universe.get_universe_types().results()
    o = esi.client.Universe.get_universe_types_type_id(type_id=34562)
    o.results()

if __name__ == '__main__':
    print('Script started...')
    main()
    print('DONE')
