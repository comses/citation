import io

from citation.export_data import PublicationCSVExporter
from citation.models import Publication, Platform, Sponsor, Author, Container
from .common import BaseTest


# Test for export_data file
class TestExport(BaseTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.csv_generator = PublicationCSVExporter()

    def setUp(self):
        self.user = self.create_user(username='bobsmith',
                                     email='a@b.com', password='test')
        self.author = Author.objects.create(given_name='Bob', family_name='Smith', type=Author.INDIVIDUAL)
        self.container = Container.objects.create(name='JASSS')
        self.platform = Platform.objects.create(name='NetLogo')
        self.publications = [Publication(title='Foo', added_by=self.user, container=self.container),
                            Publication(title='Bar', added_by=self.user, container=self.container)]
        Publication.objects.bulk_create(self.publications)

    def test_export_data(self):
        output = io.StringIO()
        self.csv_generator.write_all(output)

        contents = output.getvalue()
        publications = Publication.api.primary(prefetch=True)

        for pub in publications:
            rows = self.csv_generator.get_row(pub)
            for row in rows:
                if row is not None:
                    self.assertIn(str(row), contents)
        output.close()

    # Test if boolean list for sponsors/platforms is generating proper output or not for export data
    def test_dummy_encoding(self):
        all_platforms = ['NetLogo', 'MatLab', 'Repast']
        all_sponsors = ['National Bank of Belgium', 'European Commission',
                    'United Kingdom Engineering and Physical Sciences Research Council (EPSRC)']

        encoded_platforms = self.csv_generator.dummy_encode(all_platforms, ['NetLogo'])
        self.assertListEqual(encoded_platforms, ['1', '0', '0'])
