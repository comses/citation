FROM comses/base

RUN apk add -q --no-cache musl-dev gcc python3-dev libxml2-dev libxslt-dev build-base pcre-dev linux-headers \
# utility dependencies
        curl git bash

RUN echo @edge http://nl.alpinelinux.org/alpine/edge/main >> /etc/apk/repositories \
        && apk add postgresql-client@edge postgresql@edge postgresql-dev@edge --update-cache --no-cache -q

ENV PYTHONUNBUFFERED 1
COPY requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements.txt

WORKDIR /code
CMD /code/docker/wait-for-it.sh db:5432 -- python run_tests.py
