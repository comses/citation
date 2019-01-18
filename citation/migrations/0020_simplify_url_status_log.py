# Generated by Django 2.0.10 on 2019-01-18 23:06

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('citation', '0019_separate_code_archive_urls_from_publications'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='urlstatuslog',
            name='publication',
        ),
        migrations.RemoveField(
            model_name='urlstatuslog',
            name='type',
        ),
        migrations.RemoveField(
            model_name='urlstatuslog',
            name='url',
        ),
        migrations.AddField(
            model_name='urlstatuslog',
            name='code_archive_url',
            field=models.ForeignKey(default=-1, on_delete=django.db.models.deletion.PROTECT, to='citation.CodeArchiveUrl'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='codearchiveurl',
            name='category',
            field=models.CharField(choices=[('COMSES', 'CoMSES'), ('OPEN SOURCE', 'Open Source'), ('PLATFORM', 'Platform'), ('JOURNAL', 'Journal'), ('PERSONAL', 'Personal'), ('INVALID', 'Invalid'), ('OTHERS', 'Others'), ('', 'Empty')], default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='codearchiveurl',
            name='status',
            field=models.CharField(choices=[('available', 'Available'), ('restricted', 'Restricted'), ('unavailable', 'Unavailable')], max_length=100),
        ),
    ]
