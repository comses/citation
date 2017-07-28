#!/usr/bin/env python3

import os
import sys

import logging

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tests.settings')
    from django.core.management import execute_from_command_line
    cmd = sys.argv.pop(0)
    execute_from_command_line([cmd, "makemigrations", "citation", "--noinput"] + sys.argv)
