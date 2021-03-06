# -*- coding: utf-8 -*-
# Generated by Django 1.10 on 2016-10-27 17:45
from __future__ import unicode_literals

import citation.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('citation', '0009_make_external_ids_nonempty'),
    ]

    operations = [
        migrations.AlterField(
            model_name='author',
            name='orcid',
            field=citation.fields.NonEmptyTextField(max_length=200, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='author',
            name='researcherid',
            field=citation.fields.NonEmptyTextField(max_length=100, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='container',
            name='eissn',
            field=citation.fields.NonEmptyTextField(max_length=200, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='container',
            name='issn',
            field=citation.fields.NonEmptyTextField(max_length=200, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='publication',
            name='doi',
            field=citation.fields.NonEmptyTextField(max_length=255, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='publication',
            name='isi',
            field=citation.fields.NonEmptyTextField(max_length=255, null=True, unique=True),
        ),
    ]
