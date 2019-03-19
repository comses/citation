import logging

import requests
from urllib3.util import parse_url

from .models import Publication, URLStatusLog, CodeArchiveUrl, CodeArchiveUrlPattern, CodeArchiveUrlCategory

logger = logging.getLogger(__name__)

""" 
    Contains definition that are used to 
       - test the code archive urls are valid and up 
       - Categorize them 
       - Logs them in the URLStatusLog table

"""


def verify_url_status():
    code_archive_urls = CodeArchiveUrl.objects.all()
    fallback_category = CodeArchiveUrlCategory.objects.get(category='Unknown')
    patterns = CodeArchiveUrlPattern.objects.select_related('category').with_matchers()

    for code_archive_url in code_archive_urls:
        logger.info("Pinging: " + code_archive_url.url)
        ping_url(code_archive_url, patterns, fallback_category=fallback_category)


def ping_url(code_archive_url, patterns, fallback_category):
    url = code_archive_url.url

    category = categorize_url(url, patterns, fallback_category=fallback_category)
    try:
        s = requests.Session()
        # HEAD requests hang on some URLs so using GET for now
        r = requests.Request('GET', url)
        resp = s.send(r.prepare())
        resp.raise_for_status()
        add_url_status_log(code_archive_url, category, resp, 'available')

    except requests.exceptions.HTTPError as err:
        if err.response.status_code == 403:
            add_url_status_log(code_archive_url, category, err.response, 'restricted')
        else:
            # URL Not found (Private access)
            add_url_status_log(code_archive_url, category, err.response, 'unavailable')

    except requests.exceptions.RequestException as e:
        # Server not reachable
        add_url_status_log_bad_request(code_archive_url, category)


"""
    Categorize the url depending on the server name into following categories
    CoMSES, Open Source, Platforms, Journal, Personal, Others, and Invalid
"""


def categorize_url(url, patterns, fallback_category):
    parsed_url = parse_url(url)
    host = parsed_url.host
    path = parsed_url.path

    for pattern in patterns:
        host_matcher = pattern.host_matcher
        path_matcher = pattern.path_matcher

        if host_matcher.match(host) and path_matcher.match(path):
            logger.info('Categorized url %s as %s', url, pattern.category)
            return pattern.category
    logger.info('Categorized url %s as %s', url, fallback_category)
    return fallback_category


"""
    ADDS the logs to the status log table
"""


def add_url_status_log(code_archive_url: CodeArchiveUrl, category, request, status):
    url_status_log = URLStatusLog.objects.create(status_code=request.status_code,
                                                 publication=code_archive_url.publication,
                                                 status_reason=request.reason, headers=request.headers,
                                                 url=code_archive_url.url)
    changes = {}
    if code_archive_url.status != status:
        changes['status'] = {'old': code_archive_url.status, 'new': status}
        code_archive_url.status = status
    if code_archive_url.system_overridable_category and code_archive_url.category != category:
        changes['category'] = {'old': code_archive_url.category, 'new': category}
        code_archive_url.category = category
    if changes:
        logger.info('URL status (%s): %s %s', code_archive_url.publication.title[:25], code_archive_url.url, changes)
        code_archive_url.save()


def add_url_status_log_bad_request(code_archive_url: CodeArchiveUrl, category):
    url_status_log = URLStatusLog.objects.create(status_code=500,
                                                 publication=code_archive_url.publication,
                                                 url=code_archive_url.url)
    changes = {}
    status = 'unavailable'
    if code_archive_url.status != status:
        changes['status'] = {'old': code_archive_url.status, 'new': status}
        code_archive_url.status = status
    if code_archive_url.system_overridable_category and code_archive_url.category != category:
        changes['category'] = {'old': code_archive_url.category, 'new': category}
        code_archive_url.category = category
    if changes:
        logger.info('URL status (%s): %s %s', code_archive_url.publication.title[:25], code_archive_url.url, changes)
        code_archive_url.save()
