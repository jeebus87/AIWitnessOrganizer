web: bash start.sh
worker: celery -A app.worker.celery_app worker --loglevel=info --autoscale=100,8
beat: celery -A app.worker.celery_app beat --loglevel=info
