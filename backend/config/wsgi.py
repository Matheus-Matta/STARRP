from django.core.wsgi import get_wsgi_application

from config.environment import use_settings

use_settings()
application = get_wsgi_application()
