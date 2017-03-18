# -*- coding: utf-8 -*-
#
# Copyright (c) 2007-2012 Noah Kantrowitz <noah@coderanger.net>
# Copyright (c) 2013-2016 Ryan J Ollos <ryan.j.ollos@gmail.com>
#
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import shutil
import tempfile
import unittest

from trac.test import EnvironmentStub, Mock


class TicketLinksTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   enable=['trac.*', 'mastertickets.*'])
        self.env.path = tempfile.mkdtemp()
        self.req = Mock()

    def tearDown(self):
        self.env.shutdown()
        shutil.rmtree(self.env.path)


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TicketLinksTestCase, 'test'))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
