#!/usr/bin/env python3

from distutils.core import setup

setup(name='comses-citation',
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
      author_email='comses@asu.edu',
      install_requires=[req for req in open('requirements.txt').readlines() if req],
      license='GPL3',
      packages=['citation'],
      zip_safe=False
      )


