web: bash start.sh
worker: celery -A app.worker.celery_app worker -B --loglevel=info --autoscale=100,8
