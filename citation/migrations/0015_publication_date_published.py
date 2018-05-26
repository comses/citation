from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('citation', '0014_add_url_status_logs_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='publication',
            name='date_published',
            field=models.DateField(null =True, blank=True),
        ),
    ]