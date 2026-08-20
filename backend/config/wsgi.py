"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()

# Load the URLconf NOW, while the worker is still single-threaded. Django
# imports it lazily on the first request, and with threaded gunicorn two
# simultaneous requests (Render's health checks) can race that import and
# crash with a phantom "partially initialized module" ImportError.
from django.urls import get_resolver  # noqa: E402

get_resolver().url_patterns  # noqa: B018 -- evaluating the property does the import
