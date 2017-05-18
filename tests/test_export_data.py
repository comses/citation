from django.test import TestCase

from citation.export_data import create_csv, generate_csv_row
from citation.models import Publication

from autofixture import AutoFixture

import io
import csv


# Test for export_data file
class TestExport(TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestExport, cls).setUpClass()
        cls.publication = AutoFixture(Publication, generate_fk=['container', 'added_by']).create(1)

    # Test if actual data is persisting in the file or not
    def test_export_data(self):
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        create_csv(writer=writer)

        contents = output.getvalue()

        pub = Publication.objects.get(pk=1)

        row = generate_csv_row(pub)
        for output in row:
            if output is not None:
                self.assertIn(str(output), contents)
