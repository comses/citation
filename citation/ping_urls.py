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
    category = categorize_url(url)
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


# FIXME This may not be the best way to categorize url - in future categorization will be added manually while updating
def categorize_url(url):
    if 'sourceforge.net/' in url:
        model_platform_type = CodePlatformIdentifier.SourceForge
    elif 'ccpforge.cse.rl.ac.uk/' in url:
        model_platform_type = CodePlatformIdentifier.CCPForge
    elif 'bitbucket.org/' in url:
        model_platform_type = CodePlatformIdentifier.BitBucket
    elif 'code.google.com/' in url:
        model_platform_type = CodePlatformIdentifier.GoogleCode


    elif 'www.openabm.org/' in url \
            or 'www.comses.net/' in url:
        model_platform_type = CodePlatformIdentifier.CoMSES
    elif 'zenodo.org/' in url:
        model_platform_type = CodePlatformIdentifier.Zenodo
    elif 'figshare.com/' in url:
        model_platform_type = CodePlatformIdentifier.Figshare
    elif 'dataverse.harvard.edu/' in url:
        model_platform_type = CodePlatformIdentifier.Dataverse
    elif 'osf.io/' in url:
        model_platform_type = CodePlatformIdentifier.OSF

    elif "modelingcommons.org/" in url \
            or "ccl.northwestern.edu/netlogo/models/community" in url:
        model_platform_type = CodePlatformIdentifier.NetLogo
    elif "cormas.cirad.fr/" in url:
        model_platform_type = CodePlatformIdentifier.CORMAS

    elif 'sciencedirect.com' in url:
        model_platform_type = CodePlatformIdentifier.Journal
    elif "journals.plos.org" in url:
        model_platform_type = CodePlatformIdentifier.Journal

    elif "dropbox.com" in url:
        model_platform_type = CodePlatformIdentifier.DropBox
    elif "researchgate.net" in url:
        model_platform_type = CodePlatformIdentifier.ResearchGate
    else:
        model_platform_type = CodePlatformIdentifier.Empty

    return model_platform_type.value


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
