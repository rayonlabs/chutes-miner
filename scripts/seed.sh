#! /bin/bash
echo 'Waiting for database to be ready...'
until psql -c 'SELECT 1' > /dev/null 2>&1; do
  echo 'Database not ready yet, waiting...'
  sleep 2;
done
echo 'Database is ready, running seed script...'
python /app/scripts/seed.py