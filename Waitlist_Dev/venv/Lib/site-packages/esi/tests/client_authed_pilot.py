# flake8: noqa
"""script for testing client with live requests to ESI

This script is doing an authed request and required at least one valid token to be stored in the database. To create a valid token you can simple run through
the esi test app once.

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
from esi.models import Token
from esi.clients import EsiClientProvider

cache.clear()
esi = EsiClientProvider()

logger = logging.getLogger('__name__')
logger.level = logging.DEBUG


def main():
    token = Token.objects.filter(scopes__name='esi-characters.read_medals.v1').first()
    response = (
        esi.client.Character
        .get_characters_character_id_medals(
            character_id=token.character_id,
            token=token.valid_access_token()
        )
        .result()
    )

if __name__ == '__main__':
    print('Script started...')
    main()
    print('DONE')
