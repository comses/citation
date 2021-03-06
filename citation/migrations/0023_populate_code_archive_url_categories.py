# Generated by Django 2.0.10 on 2019-02-15 20:25

from django.db import migrations


CATEGORIES = [
    ('Archive', 'CoMSES', [(r'comses\.net|www\.comses\.net|www\.openabm\.org', '')]),
    ('Archive', 'Dataverse', [(r'dataverse\.harvard\.edu', '')]),
    ('Archive', 'Figshare', [(r'figshare\.com', '')]),
    ('Archive', 'Open Science Framework', [(r'osf\.io', '')]),
    ('Archive', 'Zenodo', [(r'zenodo\.org', '')]),

    ('Code Repository', 'BitBucket', [(r'gitlab\.com', '')]),
    ('Code Repository', 'CCPForge', [(r'ccforge\.cse\.rl\.ac\.uk', '')]),
    ('Code Repository', 'GitHub', [(r'github\.com', '')]),
    ('Code Repository', 'GitLab', [(r'gitlab\.com', '')]),
    ('Code Repository', 'Google Code', [(r'code\.google\.com', '')]),
    ('Code Repository', 'Source Forge', [(r'sourceforge\.net', '')]),

    ('Journal', '', [(r'sciencedirect\.com|journals.plos.org', '')]),

    ('Personal or Organizational', 'Dropbox', [(r'dropbox\.com', '')]),
    ('Personal or Organizational', 'Google Drive', [(r'drive\.google\.com', '')]),
    ('Personal or Organizational', 'ResearchGate', [(r'researchgate\.net', '')]),
    ('Personal or Organizational', 'Own Website', [('', '')]),

    ('Platform', 'NetLogo', [
        (r'modelingcommons\.org', ''), ('ccl\.northwestern\.edu', '/netlogo/models/community/.*')]),
    ('Platform', 'Cormas', [(r'cormas\.cirad\.fr', '')]),

    ('Other', '', [('', '')]),
    ('Unknown', '', [('', '')])
]


def populate_categories(apps, schema_editor):
    CodeArchiveUrlCategory = apps.get_model('citation', 'CodeArchiveUrlCategory')
    CodeArchiveUrlPattern = apps.get_model('citation', 'CodeArchiveUrlPattern')

    code_archive_url_categories = []
    for raw_category in CATEGORIES:
        code_archive_url_category = CodeArchiveUrlCategory(category=raw_category[0],
                                                           subcategory=raw_category[1])
        code_archive_url_categories.append(code_archive_url_category)
    CodeArchiveUrlCategory.objects.bulk_create(code_archive_url_categories)

    code_archive_url_patterns = []
    for raw_category, code_archive_url_category in zip(CATEGORIES, code_archive_url_categories):
        raw_patterns = raw_category[2]
        for raw_pattern in raw_patterns:
            pattern = CodeArchiveUrlPattern(regex_host_matcher=raw_pattern[0],
                                            regex_path_matcher=raw_pattern[1],
                                            category=code_archive_url_category)
            code_archive_url_patterns.append(pattern)
    CodeArchiveUrlPattern.objects.bulk_create(code_archive_url_patterns)


def unpopulate_categories(app, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ('citation', '0022_add_related_code_archive_url_models'),
    ]

    operations = [
        migrations.RunPython(code=populate_categories, reverse_code=unpopulate_categories)
    ]
