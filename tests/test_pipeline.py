# Test the Metadata Extraction Pipeline Beginning to End

from django.contrib.auth.models import User
from django.test import TestCase

from citation import models
from citation.management.commands.load_bibtex import Command


class TestPipeline(TestCase):
    @staticmethod
    def load_data():
        cmd = Command()
        cmd.handle(filename="tests/data/all_problematic_entries.bib",
                   username='foo')

    @classmethod
    def setUpClass(cls):
        super(TestPipeline, cls).setUpClass()
        User.objects.create(username='foo', email='a@b.com', password='test')
        cls.load_data()

        cls.primary_publication = [
            'Duplicate Citations One Publication',
            'Towards realistic and effective Agent-based models of crowd dynamics',
            'Sustainability in the Malaysian palm oil industry',
            'An integrated framework of agent-based modelling and robust optimization for microgrid energy management'
        ]

        cls.secondary_publication = [
            '10.2105/ajph.2004.037705',
            '10.1016/j.apenergy.2008.09.006',
            '10.1016/j.enconman.2012.09.001',
            '10.1016/j.cnsns.2009.10.005',
        ]

        cls.duplicate_citation_one_publication_references = [
            {
                'title': 'An integrated framework of agent-based modelling and robust optimization for microgrid energy management',
                'doi': '10.1016/j.apenergy.2014.04.024'
            },
            {
                'title': '',
                'doi': '10.2105/ajph.2004.037705'
            }
        ]

        # Note that there is only one citation here. The publication with DOI 10.1177/0011128785031001004 was not
        # included because the primary publication had already appeared once in the BibTeX file and the citation
        # counts did not match
        cls.realistic_and_effective_abms_references = [
            '10.2105/ajph.2004.037705'
        ]

        cls.microgrid_energy_management_references = {'10.1016/j.apenergy.2008.09.006',
                                                      '10.1016/j.enconman.2012.09.001', '10.1016/j.cnsns.2009.10.005',
                                                      '10.1016/j.jtbi.2014.08.016'}

        cls.not_a_publication = [
            '10.1177/0011128785031001004',
        ]

        cls.container_names = [
            {'name': 'NEUROCOMPUTING', 'issn': '0925-2312'},
            {'name': 'AM J PUBLIC HEALTH', 'issn': ''},
            {'name': 'JOURNAL OF THEORETICAL BIOLOGY', 'issn': '0022-5193'},
            {'name': 'APPL ENERG', 'issn': '0306-2619'},
            {'issn': '', 'name': 'ENERG CONVERS MANAGE'},
            {'issn': '', 'name': 'COMMUN NONLINEAR SCI'},
        ]

        cls.container_alias_names = [
            'APPLIED ENERGY',
        ]

        cls.authors_with_ids_or_emails = [
            {'family_name': 'Kuznetsova', 'given_name': 'Elizaveta', 'email': 'elizaveta.kuznetsova@uvsq.fr',
             'researcherid': 'J-4492-2016', 'orcid': None},
            {'family_name': 'Li', 'given_name': 'Yan-Fu', 'email': 'yanfu.li@ecp.fr',
             'researcherid': 'B-6610-2014', 'orcid': '0000-0001-5755-7115'},
            {'family_name': 'Ruiz', 'given_name': 'Carlos', 'email': 'caruizm@est-econ.uc3m.es',
             'researcherid': 'B-2183-2012', 'orcid': '0000-0003-1663-1061'},
            {'family_name': 'Was', 'given_name': 'Jaroslaw', 'email': 'jarek@agh.edu.pl',
             'researcherid': 'B-5835-2012', 'orcid': None},
            {'family_name': 'Zio', 'given_name': 'Enrico', 'email': 'enrico.zio@ecp.fr',
             'researcherid': None, 'orcid': '0000-0002-7108-637X'},
        ]

        cls.authors_duplicate_citation_one_publication = {
            'Was',
        }

        cls.authors_sustainability_in_the_malaysian_palm_oil_industry = {
            'Choong',
            'Mckay',
        }

        cls.authors_of_realistic_and_effective_abms = {
            'Cheeseman',
            'Newgreen',
            'Landman',
        }

        cls.authors_of_microgrid_energy_management = {
            'elizaveta.kuznetsova@uvsq.fr',
            'yanfu.li@ecp.fr',
            'caruizm@est-econ.uc3m.es',
            'enrico.zio@ecp.fr',
        }

        # The current method of associating emails with authors zips authors and emails together if they are same
        # length and otherwise does not import emails. This means that some email addresses in the BibTeX do not make
        # it into the database
        cls.missing_emails = [
            'kerryl@unimelb.edu.au'
        ]

    def test_bibtex_load(self):
        # The Primary publication "Duplicate Citations One Publication" should have only one secondary publication
        # because the all secondary entries in the BibTeX file are duplicates. One secondary entry is also the
        # same publication as the last publication in the file "An integrated framework of agent-based modelling and
        # robust optimization for microgrid energy management"

        # The Publication "Towards realistic and effective Agent-based models of crowd dynamics" appears three times
        # as a primary and once as a secondary in the BibTeX file but we should only see one entry in the database

        # The Publications "Sustainability in the Malaysian palm oil industry" and "An integrated framework of
        # agent-based modelling and robust optimization for microgrid energy management" test the functionality of
        # ContainerMergeGroups to properly dedupe containers in the case where
        #
        # 1. Publication A's container is the same as Publication B's container
        # 2. Publication A is added to the DB first followed by Publication B without enough information to determine
        #    that Publication A's and Publication B's containers are the same. Then a Publication B entry is processed
        #    and merged with the Publication B in the database. This fills in enough values Publication B's container
        #    to determine that Publication A's and Publication B's container are identical so the containers are merged

        # The Publication "An integrated framework of agent-based modelling and robust optimization for microgrid
        # energy management" appears once as a primary and references "Towards realistic and effective Agent-based
        # models of crowd dynamics"

        # The Primary Publication test ensures that the "An integrated framework of agent-based modelling and robust \
        # optimization for microgrid energy management" appears in the primary list even though the BibTeX loader first
        # encounters the reference to it
        self.assertListEqual(list(p.title for p in models.Publication.objects.filter(is_primary=True)),
                             self.primary_publication)
        self.assertListEqual(list(p.doi for p in models.Publication.objects.filter(is_primary=False)),
                             self.secondary_publication)

        # This ensures that duplicate secondary publications part of the same primary publication only get added once
        self.assertListEqual(
            list(models.Publication.objects.filter(
                referenced_by__in=models.Publication.objects.filter(title='Duplicate Citations One Publication')).values('doi', 'title')),
            self.duplicate_citation_one_publication_references)
        self.assertListEqual(list(p.doi for p in models.Publication.objects.filter(
            referenced_by__in=models.Publication.objects.filter(
                title='Towards realistic and effective Agent-based models of crowd dynamics'))),
                             self.realistic_and_effective_abms_references)
        self.assertSetEqual(
            set(p.doi for p in models.Publication.objects.filter(referenced_by__in=models.Publication.objects.filter(
                title='An integrated framework of agent-based modelling and robust optimization for microgrid energy management'))),
            self.microgrid_energy_management_references)

        self.assertFalse(models.Publication.objects.filter(doi=self.not_a_publication[0]).exists())

        for c in self.container_names:
            cn = models.Container.objects.get(name=c.get('name'))
            if cn.name in ('APPL ENERG', 'NEUROCOMPUTING', 'JOURNAL OF THEORETICAL BIOLOGY'):
                self.assertTrue(cn.issn)
                self.assertEqual(cn.id, models.Container.objects.get(issn=c.get('issn')).id)

        self.assertFalse(models.ContainerAlias.objects.filter(name='APPLIED ENERGY').exists())

        # All author entries from the primary publication "An integrated framework of agent-based modelling and robust
        # optimization for microgrid energy management" should be present even though we loaded the citation first
        self.assertListEqual(list(
            models.Author.objects
                .exclude(email='')
                .order_by('family_name')
                .values('family_name', 'given_name', 'email', 'researcherid', 'orcid')),
            self.authors_with_ids_or_emails)

        self.assertSetEqual(
            set(a.family_name for a in models.Author.objects.filter(
                publications__in=models.Publication.objects.filter(doi='10.1016/j.neucom.2014.04.057'))),
            self.authors_duplicate_citation_one_publication)

        self.assertSetEqual(
            set(a.family_name for a in models.Author.objects.filter(
                publications__in=models.Publication.objects.filter(doi='10.1016/j.jclepro.2013.12.009'))),
            self.authors_sustainability_in_the_malaysian_palm_oil_industry)

        self.assertSetEqual(
            set(a.family_name for a in models.Author.objects.filter(
                publications__in=models.Publication.objects.filter(doi='10.1016/j.jtbi.2014.08.016'))),
            self.authors_of_realistic_and_effective_abms)

        self.assertSetEqual(
            set(a.email for a in models.Author.objects.filter(
                publications__in=models.Publication.objects.filter(doi='10.1016/j.apenergy.2014.04.024'))),
            self.authors_of_microgrid_energy_management)

        self.assertFalse(models.Author.objects.filter(email=self.missing_emails[0]).exists())

    def test_bibtex_load_idempotent(self):
        """Loading the same dataset into the database twice should not result in any changes to the database"""
        n_audit_command = models.AuditCommand.objects.count()
        n_publications = models.Publication.objects.count()
        n_authors = models.Author.objects.count()
        n_containers = models.Container.objects.count()
        n_raw = models.Raw.objects.count()
        self.load_data()

        self.assertEqual(n_audit_command, models.AuditCommand.objects.count())
        self.assertEqual(n_publications, models.Publication.objects.count())
        self.assertEqual(n_authors, models.Author.objects.count())
        self.assertEqual(n_containers, models.Container.objects.count())
        self.assertEqual(n_raw, models.Raw.objects.count())
