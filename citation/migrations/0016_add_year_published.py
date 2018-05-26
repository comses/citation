from __future__ import unicode_literals
from dateutil.parser import parse as datetime_parse

from django.db import migrations

SEASONED = ['WIN', 'SPR', 'SUM', 'FAL']
SEASONED_DEFAULT_DATE = {'WIN': 'DEC 01 ', 'SPR': 'MAR 01 ', 'SUM': 'JUN 01 ', 'FAL': 'AUG 01 '}

# Data Migration - Generating date_published date field attribute from date_published_text attribute of publication
def add_publication_id(apps, schema_editor):
    Publication = apps.get_model('citation', 'Publication')
    for pub in Publication.objects.all():
        date_text = pub.date_published_text
        try :
            pub.date_published = datetime_parse(date_text).date()
            pub.save()
        except ValueError:
            # checks for two date case (1) SUM 2015 (2) Mar-Apr 2015
            try:
                date_list = date_text.split(" ")
                if date_list[0] in SEASONED:
                    # Handles date cases like SUM 2015
                    pub.date_published = datetime_parse(SEASONED_DEFAULT_DATE.get(date_list[0]) + date_list[1]).date()
                    pub.save()
                else:
                   # Handles date cases like Mar-Apr 2015
                   month = date_list[0].split('-')[1]
                   pub.date_published = datetime_parse(month + " 01 " + date_list[1]).date()
                   pub.save()
            except:
                pub.date_published = None
                pub.save()



class Migration(migrations.Migration):

    dependencies = [
        ('citation', '0015_publication_date_published'),
    ]

    operations = [
        migrations.RunPython(add_publication_id),
    ]