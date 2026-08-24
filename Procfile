web: gunicorn tickettrust.wsgi:application
worker: celery -A tickettrust worker --loglevel=info
