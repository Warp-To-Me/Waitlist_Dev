# flake8: noqa
"""script for testing connection pool size with live requests to ESI

Run this script directly. Make sure to also set the environment variable
DJANGO_PROJECT_PATH and DJANGO_SETTINGS_MODULE to match your setup:

You can see the result in your main log file of your Django installation.
If your connection pool size is too small you will see the following warning in your
log file: "Connection pool is full, discarding connection: esi.evetech.net"
To pass this test successfully ESI_CONNECTION_POOL_MAXSIZE must equal to number
of MAX_WORKER (e.g. 20)

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

MAX_WORKER = 20

cache.clear()
esi = EsiClientProvider()

logger = logging.getLogger('__name__')
logger.level = logging.DEBUG
logger.propagate = True


def thread_func(type_id):
    logger.info('Fetching type with ID %d from ESI', type_id)
    esi.client.Universe.get_universe_types_type_id(type_id=type_id).result()

def main():
    print('Script started...')
    entity_ids = esi.client.Universe.get_universe_types().results()[1000:2000]
    logger.info('Start fetching %d types' , len(entity_ids))

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKER) as executor:
        executor.map(thread_func, entity_ids)

    logger.info('Finished fetching %d types', len(entity_ids))
    print('DONE')


if __name__ == '__main__':
    main()
