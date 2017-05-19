from django.test import TestCase

from citation.export_data import create_csv, generate_csv_row, generate_boolean_list
from citation.models import Publication, Platform, Sponsor

from autofixture import AutoFixture

import io
import csv


# Test for export_data file
class TestExport(TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestExport, cls).setUpClass()
        cls.publication = AutoFixture(Publication, generate_fk=['container', 'added_by']).create(10)

    # Test if actual data is persisting in the file or not
    def test_export_data(self):
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        create_csv(writer=writer)

        contents = output.getvalue()
        publications = Publication.api.primary(prefetch=True)

        for pub in publications:
            rows = generate_csv_row(pub)
            for row in rows:
                if row is not None:
                    self.assertIn(str(row), contents)
        output.close()

    # Test if boolean list for sponsors/platforms is generating proper output or not for export data
    def test_boolean_list(self):
        platforms = ['NetLogo', 'MatLab', 'Repast']
        sponsors = ['National Bank of Belgium', 'European Commission',
                    'United Kingdom Engineering and Physical Sciences Research Council (EPSRC)']
        all_platforms = Platform.objects.all().values_list("name").order_by("name")
        all_sponsors = Sponsor.objects.all().values_list("name").order_by("name")

        platforms_output = generate_boolean_list(all_platforms, platforms)
        sponsors_output = generate_boolean_list(all_sponsors, sponsors)

        for platform in all_platforms:
            if platform in platforms:
                self.assertEquals(platforms_output[platform], 1)
            self.assertEquals(platforms_output[platform], 0)

        for sponsor in all_sponsors:
            if sponsor in sponsors:
                self.assertEquals(sponsors_output[sponsor], 1)
            self.assertEquals(sponsors_output[sponsor], 0)
