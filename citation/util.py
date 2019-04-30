import logging
import re
from hashlib import sha1
from typing import Tuple

import bleach
import markdown
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models.aggregates import Aggregate
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.template.loader import get_template
from unidecode import unidecode

logger = logging.getLogger(__name__)


ALLOWED_TAGS = bleach.ALLOWED_TAGS + [
    'p', 'h1', 'h2', 'h3', 'h4', 'pre', 'br', 'hr', 'div', 'span', 'footer',
    'img', 'table', 'thead', 'tbody', 'tfoot', 'col', 'colgroup', 'th', 'tr', 'td'
]

ALLOWED_ATTRIBUTES = dict(bleach.ALLOWED_ATTRIBUTES,
                          **{'*': ['name', 'id', 'class'], 'img': ['alt', 'src']})

DEFAULT_MARKDOWN_EXTENSIONS = [
    'markdown.extensions.extra',
    'markdown.extensions.codehilite',
    'markdown.extensions.nl2br',
    'markdown.extensions.sane_lists',
    'markdown.extensions.smarty',
    'markdown.extensions.toc',
    #    'markdown.extensions.wikilinks',
]


def render_sanitized_markdown(md_text: str, extensions=None):
    if extensions is None:
        extensions = DEFAULT_MARKDOWN_EXTENSIONS
    html = markdown.markdown(
        md_text,
        extensions=extensions
    )
    return sanitize_html(html)


def sanitize_html(html: str):
    return bleach.clean(bleach.linkify(html), tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)


def create_markdown_email(subject: str=None, to=None, template_name: str=None, context: dict=None, body: str=None, from_email: str=settings.DEFAULT_FROM_EMAIL,
                          **kwargs):
    if all([template_name, context]):
        # override body if a template name and context were given to us
        try:
            template = get_template(template_name)
            body = template.render(context=context)
        except TemplateDoesNotExist:
            logger.error("couldn't find template %s", template_name)
        except TemplateSyntaxError:
            logger.error("invalid template %s", template_name)
    required_fields = [subject, to, body, from_email]
    if all(required_fields):
        email = EmailMultiAlternatives(subject=subject, body=body, to=to, from_email=from_email, **kwargs)
        email.attach_alternative(render_sanitized_markdown(body), 'text/html')
        return email
    else:
        raise ValueError("Ignoring request to create a markdown email with missing required content {}".format(required_fields))


def send_markdown_email(**kwargs):
    # convenience method for create_markdown_email, so we just keep the same signature
    # use kwargs only, positional args for email parameters can be fraught
    create_markdown_email(**kwargs).send()


def sanitize_doi(s):
    if s:
        s = re.sub(r"\{|\}|\\", "", s)
        s = s.lower()
    return s


def sanitize_name(s):
    if s:
        s = re.sub("\{''\}|``", "\"", s)
        s = re.sub("\n", " ", s)
        s = re.sub("\\\\", "", s)
    return s


def normalize_name(name: str, strip_unicode=True) -> str:
    normalized_name = name.upper()
    normalized_name = re.sub(r"\n|\r", " ", normalized_name)
    normalized_name = re.sub(r"\.|,|\{|\}", "", normalized_name)
    if strip_unicode:
        normalized_name = unidecode(normalized_name).strip()
    else:
        normalized_name = normalized_name.strip()
    return normalized_name


def all_initials(given_names):
    return all(len(given_name) == 1 and given_name == given_name.upper()
               for given_name in given_names)


def last_name_and_initials(name: str) -> Tuple[str, str]:
    normalized_name = normalize_name(name)
    name_split = re.split(r"\b,? +\b", normalized_name)
    family = name_split[0]
    given_names = name_split[1:] if len(name_split) > 1 else []
    if all_initials(given_names):
        given = "".join(given_names)
    elif len(given_names) > 1 and any(len(given_name) > 1 for given_name in given_names):
        given = "".join(given_name[0] for given_name in given_names)
    else:
        given = " ".join(given_names)

    if given is not None:
        return family, given
    else:
        return normalized_name, ''


def last_name_and_initial(normalized_name: str) -> str:
    name_split = re.split(r"\b,? +\b", normalized_name)
    family = name_split[0]
    given_names = name_split[1:] if len(name_split) > 1 else []
    if all_initials(given_names):
        given = given_names[0][0]
    elif len(given_names) > 0 and len(given_names[0]) > 1:
        given = given_names[0][0]
    else:
        given = None

    if given is not None:
        return "{} {}".format(family, given)
    else:
        return normalized_name


class ArrayAgg(Aggregate):
    function = 'ARRAY_AGG'
    name = 'ArrayAgg'
    template = '%(function)s(%(distinct)s%(expressions)s)'

    def __init__(self, expression, distinct=False, **extra):
        super(ArrayAgg, self).__init__(expression, distinct='DISTINCT ' if distinct else '', **extra)

    def __repr__(self):
        '{}({}, distinct={})'.format(
            self.__class__.__name__,
            self.arg_joiner.join(str(arg) for arg in self.source_expressions),
            'False' if self.extra['distinct'] == '' else 'True',
        )

    def convert_value(self, value, expression, connection, context):
        if not value:
            return []
        return value


def create_timestamp_hash(timestamp: float):
    info = (str(timestamp), settings.SECRET_KEY)
    return sha1("".join(info).encode("ascii")).hexdigest()