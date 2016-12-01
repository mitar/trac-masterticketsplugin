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

from trac.db import Table, Column

name = 'mastertickets'
version = 2
tables = [
    Table('mastertickets', key=('source', 'dest'))[
        Column('source', type='integer'),
        Column('dest', type='integer'),
    ],
]
