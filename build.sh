#!/usr/bin/env bash

# Adapted from http://lukeswart.net/2016/03/lets-deploy-part-1/

set -a
source docker/.env

DB_PASSWORD=`head /dev/urandom | tr -dc A-Za-z0-9 | head -c30`
DJANGO_SECRET_KEY=`head /dev/urandom | tr -dc A-Za-z0-9 | head -c30`

cat docker/templates/django/config.ini.template | envsubst > docker/config/django/config.ini
cat docker-compose.yml.template | envsubst > docker-compose.yml
