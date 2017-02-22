FROM comses/base

RUN apt-get update && apt-get install -qq -y libxml2-dev python3-dev python3-pip libxslt1-dev curl git wget \
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ xenial-pgdg main" | tee /etc/apt/sources.list.d/postgresql.list \
    && wget -q -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && apt-get update && apt-get install -q -y postgresql-client-9.6 libpq-dev

ENV PYTHONUNBUFFERED 1
COPY requirements-dev.txt requirements.txt /tmp/
RUN pip3 install -r /tmp/requirements-dev.txt

WORKDIR /code
COPY . /code
CMD /code/docker/wait-for-it.sh db:5432 -- python3 run_tests.py
