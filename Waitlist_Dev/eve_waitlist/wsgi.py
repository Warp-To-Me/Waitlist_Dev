"""
WSGI config for eve_waitlist project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/wsgi/

---
NOTE: This file is no longer the primary server entry point.
The project has been configured to run as an ASGI application
using 'eve_waitlist/asgi.py' to support real-time features.
---
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'eve_waitlist.settings')

application = get_wsgi_application()