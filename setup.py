#!/usr/bin/env python3

from distutils.core import setup

setup(name='citation',
      version='0.0.1',
      classifiers=[
          'Environment :: Web Environment',
          'Framework :: Django :: 2.1.x',  # replace "X.Y" as appropriate
          'Intended Audience :: Developers',
          'Development Status :: 3 - Alpha',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: GPL V3 License'
          'Operating System :: OS Independent',
          'Programming Language :: Python 3.6'
      ],
      description='Citation management and deduplication for Django',
      url='https://github.com/comses/citation',
      author='CoMSES',
      author_email='devs@comses.net',
      install_requires=[
          'Django>=2.0,<3.0',
          'djangorestframework>=3.7,<4.0',
          'python-dateutil',
          'bleach',
          'fuzzywuzzy',
          'lxml',
          'markdown',
          'bibtexparser',
          'pyzotero',
          'django-extensions',
          'django-model-utils',
          'pyparsing==2.3.0',
          'psycopg2-binary',
          'requests',
          'Unidecode',
          'python-Levenshtein',
          'numpy',
          'scipy',
          'pandas'
      ],
      test_requires=[
          'django-autofixture',
          'coverage',
          'python-coveralls',
      ],
      license='GPL3',
      packages=['citation'],
      zip_safe=False
      )
