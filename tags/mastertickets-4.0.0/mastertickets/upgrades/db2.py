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

from trac.db.api import DatabaseManager

from mastertickets import db_default


def do_upgrade(env, ver, cursor):
    dbm = DatabaseManager(env)
    temp_table_name = db_default.name + '_old'
    with env.db_transaction as db:
        db("""CREATE TEMPORARY TABLE %s AS SELECT * FROM %s
            """ % (temp_table_name, db_default.name))
        dbm.drop_tables((db_default.name,))
        dbm.create_tables(db_default.tables)
        for source, dest in db("""
                SELECT source, dest FROM %s
                """ % temp_table_name):
            try:
                db("""
                    INSERT INTO %s (source,dest) VALUES (%%s,%%s)
                    """ % db_default.name, (int(source), int(dest)))
            except Exception:
                env.log.warning("Error inserting source, dest = %s, %s",
                                source, dest)
        dbm.drop_tables((temp_table_name,))
