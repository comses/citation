# -*- coding: utf-8 -*-
# Generated by Django 1.10 on 2016-09-20 15:46
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('citation', '0004_move_flagged_status_to_flagged_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='author',
            name='researcherid',
            field=models.TextField(default='', max_length=100),
        ),
        migrations.AddField(
            model_name='container',
            name='eissn',
            field=models.TextField(blank=True, default='', max_length=200),
        ),
        migrations.AlterField(
            model_name='container',
            name='issn',
            field=models.TextField(blank=True, default='', max_length=200),
        ),
    ]
