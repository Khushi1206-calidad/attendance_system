"""WSGI entry point for deployments that use a WSGI server such as gunicorn."""

import os

from django.core.wsgi import get_wsgi_application

from attendance.services.logging_config import configure_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
configure_logging()

application = get_wsgi_application()
