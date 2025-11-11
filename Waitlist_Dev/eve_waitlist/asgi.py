"""
ASGI config for eve_waitlist project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os
import django
from django.core.asgi import get_asgi_application
# Import channels middleware
from channels.routing import ProtocolTypeRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'eve_waitlist.settings')
django.setup()

# This must be called *after* django.setup()
django_asgi_app = get_asgi_application()

# This router wraps the main Django app
# It adds session/auth data to all HTTP requests,
# which django-eventstream needs to work correctly.
application = ProtocolTypeRouter({
    "http": AuthMiddlewareStack(django_asgi_app),
    # We are not using WebSockets yet
})