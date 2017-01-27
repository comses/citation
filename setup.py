#!/usr/bin/env python3

from distutils.core import setup

setup(name='citation',
      version='0.0.1',
      classifiers=[
          'Development Status :: 3 - Alpha',

          'Intended Audience :: Developers',

          'License :: OSI Approved :: GPL V3 License'

          'Programming Language :: Python 3.5'
      ],
      description='Citation management and deduplication for Django',
      url='https://github.com/comses/citation',
      author='CoMSES',
      author_email='devs@comses.net',
      install_requires=[
          'Django>=1.10,<1.11',
          'djangorestframework>=3.5,<3.6',
          'fuzzywuzzy>=0.14,<0.15',
          'lxml>=3.7,<3.8',
          'bibtexparser',
          'pyzotero',
          'django-extensions',
          'django-kronos',
          'django-model-utils',
          'psycopg2',
          'requests',
          'unidecode',
          'python-Levenshtein',
      ],
      license='GPL3',
      packages=['citation'],
      zip_safe=False
      )
