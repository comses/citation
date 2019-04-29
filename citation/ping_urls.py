import logging

from .models import CodeArchiveUrl, CodeArchiveUrlPattern, CodeArchiveUrlCategory

logger = logging.getLogger(__name__)


def verify_url_status():
    """ requests all CodeArchiveUrls to check their status """
    code_archive_urls = CodeArchiveUrl.objects.all()
    patterns = CodeArchiveUrlPattern.objects.select_related('category').with_matchers()
    fallback_category = CodeArchiveUrlCategory.objects.get(category='Unknown')
    logger.info("Verifying URL status for all CodeArchiveURLs with %s patterns and fallback category [%s]",
                patterns.count(),
                fallback_category)

    for code_archive_url in code_archive_urls:
        logger.info("Checking status of %s", code_archive_url)
        code_archive_url.check_status(patterns, fallback_category=fallback_category)
