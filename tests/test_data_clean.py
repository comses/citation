import logging

from citation import dedupe, models
from django.contrib.auth.models import User
from django.test import TestCase

logger = logging.getLogger(__name__)


class SplitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        super(SplitTests, cls).setUpTestData()
        cls.name = "C#/.NET"

        cls.user = User.objects.create_user(username='bob',
                                            email='bob@bob.com',
                                            password='bobsled')

        container = models.Container.objects.create(issn='', name='jasss')
        platform = models.Platform.objects.create(name=cls.name)
        publication = models.Publication.objects.create(title="Foo", added_by=cls.user, container=container)
        models.PublicationPlatforms.objects.create(publication=publication, platform=platform)

        cls.container = container
        cls.platform_dotnet = platform
        cls.publication_dotnet = publication

    def test_split_platform_different_new_names(self):
        new_names = ["C#", ".NET"]
        processor = dedupe.DataProcessor(models.Platform, creator=self.user)
        processor.split_record(name=self.name, new_names=new_names)

        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#/.NET").first(), None)

    def test_split_platform_same_new_name(self):
        new_names = ["C#/.NET", ".NET"]
        processor = dedupe.DataProcessor(models.Platform, creator=self.user)
        processor.split_record(name=self.name, new_names=new_names)

        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#/.NET").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 1)

    def test_split_plat_multiple_publications(self):
        platform_netlogo = models.Platform.objects.create(name="NetLogo")
        publication_netlogo_dotnet = models.Publication.objects.create(title="Bar", added_by=self.user,
                                                                       container=self.container)
        publication_netlogo = models.Publication.objects.create(title="Baz", added_by=self.user,
                                                                container=self.container)

        models.PublicationPlatforms.objects.create(publication=publication_netlogo_dotnet,
                                                   platform=platform_netlogo)
        models.PublicationPlatforms.objects.create(publication=publication_netlogo_dotnet,
                                                   platform=self.platform_dotnet)

        models.PublicationPlatforms.objects.create(publication=publication_netlogo,
                                                   platform=platform_netlogo)

        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name="C#").count(), 0)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 0)
        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name=self.name).first(), self.platform_dotnet)
        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name="NetLogo").first(), platform_netlogo)

        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#").count(), 0)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 0)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=self.name).first(), self.platform_dotnet)
        self.assertEqual(self.publication_dotnet.platforms.filter(name="NetLogo").first(), None)

        self.assertEqual(publication_netlogo.platforms.filter(name="C#").count(), 0)
        self.assertEqual(publication_netlogo.platforms.filter(name=".NET").count(), 0)
        self.assertEqual(publication_netlogo.platforms.filter(name=self.name).first(), None)
        self.assertEqual(publication_netlogo.platforms.filter(name="NetLogo").first(), platform_netlogo)

        processor = dedupe.DataProcessor(models.Platform, creator=self.user)
        processor.split_record(name=self.name, new_names=["C#", ".NET"])

        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name="C#").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 1)
        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name=self.name).first(), None)
        self.assertEqual(publication_netlogo_dotnet.platforms.filter(name="NetLogo").first(), platform_netlogo)

        self.assertEqual(self.publication_dotnet.platforms.filter(name="C#").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=".NET").count(), 1)
        self.assertEqual(self.publication_dotnet.platforms.filter(name=self.name).first(), None)
        self.assertEqual(self.publication_dotnet.platforms.filter(name="NetLogo").first(), None)

        self.assertEqual(publication_netlogo.platforms.filter(name="C#").count(), 0)
        self.assertEqual(publication_netlogo.platforms.filter(name=".NET").count(), 0)
        self.assertEqual(publication_netlogo.platforms.filter(name=self.name).first(), None)
        self.assertEqual(publication_netlogo.platforms.filter(name="NetLogo").first(), platform_netlogo)


class MergeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        super(MergeTests, cls).setUpTestData()
        cls.names = ["Euro. Commission", "EC"]

        cls.user = User.objects.create_user(username='bob',
                                            email='bob@bob.com',
                                            password='bobsled')

        container = models.Container.objects.create(issn='', name='jasss')
        sponsors = [models.Sponsor.objects.create(name=name) for name in cls.names]
        publication = models.Publication.objects.create(title="Foo", added_by=cls.user, container=container)
        publicationsponsors = [models.PublicationSponsors(publication=publication, sponsor=sponsor) for sponsor in
                               sponsors]
        models.PublicationSponsors.objects.bulk_create(publicationsponsors)

        cls.container = container
        cls.publication = publication
        cls.sponsors = sponsors

    def test_merge_platform_different_new_name(self):
        new_name = "European Commission"
        processor = dedupe.DataProcessor(models.Sponsor, creator=self.user)
        new_sponsor = processor.merge_records(names=self.names, new_name=new_name)

        self.assertEqual(self.publication.sponsors.filter(name__in=self.names).first(), None)
        self.assertEqual(self.publication.sponsors.get(name=new_name), new_sponsor)

    def test_merge_platform_same_new_name(self):
        new_name = "Euro. Commission"
        processor = dedupe.DataProcessor(models.Sponsor, creator=self.user)
        new_sponsor = processor.merge_records(names=self.names, new_name=new_name)

        self.assertEqual(self.publication.sponsors.filter(name__in=self.names).first(), new_sponsor)
        self.assertEqual(self.publication.sponsors.get(name=new_name), new_sponsor)

    def test_merge_sponsor_multiple_publications(self):
        sponsor_euro_commission = self.sponsors[0]
        sponsor_nsf = models.Sponsor.objects.create(name="United States National Science Foundation (NSF)")

        publication_euro_commission_nsf = models.Publication.objects.create(title="Foo", added_by=self.user,
                                                                            container=self.container)
        models.PublicationSponsors.objects.create(publication=publication_euro_commission_nsf,
                                                  sponsor=sponsor_euro_commission)
        models.PublicationSponsors.objects.create(publication=publication_euro_commission_nsf,
                                                  sponsor=sponsor_nsf)

        publication_nsf = models.Publication.objects.create(title="Bar", added_by=self.user, container=self.container)
        models.PublicationSponsors.objects.create(publication=publication_nsf,
                                                  sponsor=sponsor_nsf)

        new_name = "Euro. Commission"
        processor = dedupe.DataProcessor(models.Sponsor, creator=self.user)
        new_sponsor = processor.merge_records(names=self.names, new_name=new_name)

        self.assertEqual(models.Sponsor.objects.filter(name=new_name).first(), new_sponsor)
        self.assertEqual(sponsor_euro_commission, new_sponsor)
        self.assertEqual(models.Sponsor.objects.filter(name=self.names[1]).first(), None)

        self.assertCountEqual(list(publication_euro_commission_nsf.sponsors.all()),
                              [sponsor_nsf, new_sponsor])
        self.assertCountEqual(list(publication_nsf.sponsors.all()),
                              [sponsor_nsf])
        self.assertCountEqual(list(self.publication.sponsors.all()),
                              [new_sponsor])
