import logging
import requests

from django.db.models import Q

from citation.models import Publication, URLStatusLogs, PlatformTypes

logger = logging.getLogger(__name__)

""" 
    Contains definition that are used to 
       - test the code archive urls are valid and up 
       - Categorize them 
       - Logs them in the URLStatusLog table

"""


def verify_url_status():
    publication = Publication.objects.filter(~Q(code_archive_url = ''), is_primary = "True", status= "REVIEWED")

    for pub in publication:
        logger.debug("Pinging: " + pub.code_archive_url)
        ping_url(pub.pk, pub.code_archive_url)

def ping_url(pk, url):
    try:
        s = requests.Session()
        r = requests.Request('GET', url)
        resp = s.send(r.prepare())
        resp.raise_for_status()
        platform_type = categorize_url(url)
        add_url_status_log(pk, platform_type, resp)

    except requests.exceptions.HTTPError as err:
        # URL Not found or forbidden (Private access)
        add_url_status_log(pk, PlatformTypes.INVALID, err.response)

    except requests.exceptions.RequestException as e:
        # Server not reachable
        add_url_status_log_bad_request(pk, PlatformTypes.INVALID, url)

"""
    Categorize the url depending on the server name into following categories 
    CoMSES, Open Source, Platforms, Journal, Personal, Others, and Invalid
"""
# FIXME This may not be the best way to categorize url - in future categorization will be added manually while updating
def categorize_url(url):

    if "www.openabm.org/" in url \
            or "www.comses.net" in url :
        model_platform_type = PlatformTypes.COMSES

    elif "sourceforge.net/" in url or "github.com/" in url \
            or "ccpforge.cse.rl.ac.uk/" in url \
            or "bitbucket.org/" in url \
            or "dataverse.harvard.edu/" in url \
            or "code.google.com/" in url \
            or "sciencedirect.com" in url \
            or "figshare.com" in url:
        model_platform_type = PlatformTypes.OPEN_SOURCE

    elif "modelingcommons.org/" in url \
            or "ccl.northwestern.edu/netlogo/models/community" in url \
            or "cormas.cirad.fr/" in url:
        model_platform_type = PlatformTypes.PLATFORM

    elif "journals.plos.org" in url:
        model_platform_type = PlatformTypes.JOURNAL

    elif "dropbox.com" in url \
            or "researchgate.net" in url \
            or ".zip" in url or ".pdf" in url \
            or ".txt" in url or '.docx' in url:
        model_platform_type = PlatformTypes.PERSONAL

    else:
        model_platform_type = PlatformTypes.OTHERS

    return model_platform_type

""" 
    ADDS the logs to the status log table
"""
def add_url_status_log(pk, type, request):
    url_log_object = URLStatusLogs.objects.create(type=type, status_code=request.status_code,
                                                  status_reason= request.reason, url=request.url, text= request.headers)
    url_log_object.pub_id = Publication.objects.get(pk=pk)
    url_log_object.save()

def add_url_status_log_bad_request(pk, type, url):
    url_log_object = URLStatusLogs.objects.create(type=type, url=url, status_code = 500)
    url_log_object.pub_id = Publication.objects.get(pk=pk)
    url_log_object.save()