import re

from django.db import migrations

BATCH_SIZE = 1000
YEAR_PUBLISHED_REGEX = re.compile(r"(?<!\d)\d{4}(?!\d)")


def backfill_year_published(apps, schema_editor):
    Publication = apps.get_model("citation", "Publication")
    publications = (
        Publication.objects.exclude(date_published_text="")
        .only("pk", "date_published_text")
        .iterator(chunk_size=BATCH_SIZE)
    )
    batch = []
    for pub in publications:
        match = YEAR_PUBLISHED_REGEX.search(pub.date_published_text)
        if match is None:
            continue
        pub.year_published = int(match.group(0))
        batch.append(pub)
        if len(batch) >= BATCH_SIZE:
            Publication.objects.bulk_update(batch, ["year_published"])
            batch = []
    Publication.objects.bulk_update(batch, ["year_published"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("citation", "0037_publication_year_published"),
    ]

    operations = [
        migrations.RunPython(backfill_year_published, noop),
    ]
