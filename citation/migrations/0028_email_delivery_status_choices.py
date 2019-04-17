# Generated by Django 2.2 on 2019-04-17 22:00

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('citation', '0027_add_author_correspondence_log'),
    ]

    operations = [
        migrations.AlterField(
            model_name='authorcorrespondencelog',
            name='email_delivery_status',
            field=models.CharField(choices=[('sent', 'Author correspondence successfully sent'), ('error', 'Unable to send email, see error log for details'), ('not_sent', 'Correspondence has not been sent yet')], default='not_sent', max_length=50),
        ),
        migrations.AlterField(
            model_name='suggestedmerge',
            name='content_type',
            field=models.ForeignKey(limit_choices_to=models.Q(('app_label', 'citation'), ('model__in', ['author', 'container', 'platform', 'publication', 'sponsor'])), on_delete=django.db.models.deletion.PROTECT, related_name='suggested_merge_set', to='contenttypes.ContentType'),
        ),
    ]
