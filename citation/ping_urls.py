import logging

import requests
from django.db.models import Q

from .graphviz.globals import CodePlatformIdentifier
from .models import Publication, URLStatusLog, CodeArchiveUrl

logger = logging.getLogger(__name__)

""" 
    Contains definition that are used to 
       - test the code archive urls are valid and up 
       - Categorize them 
       - Logs them in the URLStatusLog table

"""


def verify_url_status():
    code_archive_urls = CodeArchiveUrl.objects.all()

    for code_archive_url in code_archive_urls:
        logger.info("Pinging: " + code_archive_url.url)
        ping_url(code_archive_url)


def ping_url(code_archive_url):
    url = code_archive_url.url
    try:
        s = requests.Session()
        # HEAD requests hang on some URLs so using GET for now
        r = requests.Request('GET', url)
        resp = s.send(r.prepare())
        resp.raise_for_status()
        category = categorize_url(url)
        add_url_status_log(code_archive_url, category, resp)

    except requests.exceptions.HTTPError as err:
        # URL Not found or forbidden (Private access)
        add_url_status_log(code_archive_url, CodePlatformIdentifier.INVALID.value, err.response)

    except requests.exceptions.RequestException as e:
        # Server not reachable
        add_url_status_log_bad_request(code_archive_url, CodePlatformIdentifier.INVALID.value)


"""
    Categorize the url depending on the server name into following categories 
    CoMSES, Open Source, Platforms, Journal, Personal, Others, and Invalid
"""


# FIXME This may not be the best way to categorize url - in future categorization will be added manually while updating
def categorize_url(url):
    if "www.openabm.org/" in url \
            or "www.comses.net" in url:
        model_platform_type = CodePlatformIdentifier.COMSES.value

    elif "sourceforge.net/" in url or "github.com/" in url \
            or "ccpforge.cse.rl.ac.uk/" in url \
            or "bitbucket.org/" in url \
            or "dataverse.harvard.edu/" in url \
            or "code.google.com/" in url \
            or "sciencedirect.com" in url \
            or "figshare.com" in url:
        model_platform_type = CodePlatformIdentifier.OPEN_SOURCE.value

    elif "modelingcommons.org/" in url \
            or "ccl.northwestern.edu/netlogo/models/community" in url \
            or "cormas.cirad.fr/" in url:
        model_platform_type = CodePlatformIdentifier.PLATFORM.value

    elif "journals.plos.org" in url:
        model_platform_type = CodePlatformIdentifier.JOURNAL.value

    elif "dropbox.com" in url \
            or "researchgate.net" in url \
            or ".zip" in url or ".pdf" in url \
            or ".txt" in url or '.docx' in url:
        model_platform_type = CodePlatformIdentifier.PERSONAL.value

    else:
        model_platform_type = CodePlatformIdentifier.OTHERS.value

    return model_platform_type


""" 
    ADDS the logs to the status log table
"""


def add_url_status_log(code_archive_url: CodeArchiveUrl, category, request):
    url_status_log = URLStatusLog.objects.create(status_code=request.status_code,
                                                 publication=code_archive_url.publication,
                                                 status_reason=request.reason, headers=request.headers,
                                                 url=code_archive_url.url)
    if not code_archive_url.category:
        code_archive_url.category = category
        code_archive_url.save()


def add_url_status_log_bad_request(code_archive_url, category):
    url_status_log = URLStatusLog.objects.create(status_code=500,
                                                 publication=code_archive_url.publication,
                                                 url=code_archive_url.url)

    if not code_archive_url.category:
        code_archive_url.category = category
        code_archive_url.save()
