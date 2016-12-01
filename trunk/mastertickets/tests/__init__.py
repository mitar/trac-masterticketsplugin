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

import unittest


def suite():
    from mastertickets.tests import model
    suite = unittest.TestSuite()
    suite.addTest(model.suite())
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
