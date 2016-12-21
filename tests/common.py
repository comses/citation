from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.utils.http import urlencode

import logging

logger = logging.getLogger(__name__)


class BaseTest(TestCase):
    default_username = 'testcase'
    default_email = 'testcase@mailinator.com'
    default_password = 'testing'

    def setUp(self):
        self.user = self.create_user()

    def create_user(self, username=None, email=None, password=None, **kwargs):
        if username is None:
            username = self.default_username
        if email is None:
            email = self.default_email
        if password is None:
            password = self.default_password
        return User.objects.create_user(username=username, email=email, password=password, **kwargs)

    def login(self, username=None, password=None):
        if username is None:
            username = self.default_username
        if password is None:
            password = self.default_password
        return self.client.login(username=username, password=password)

    def logout(self):
        return self.client.logout()
