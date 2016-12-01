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

import copy
import datetime

from trac.ticket.model import Ticket
from trac.util.datefmt import utc, to_utimestamp

from mastertickets.compat import to_list


class TicketLinks(object):
    """A model for the ticket links used MasterTickets."""

    def __init__(self, env, tkt):
        self.env = env
        if not isinstance(tkt, Ticket):
            tkt = Ticket(self.env, tkt)
        self.tkt = tkt

        self.blocking = set()
        for dest, in self.env.db_query("""
                SELECT dest FROM mastertickets WHERE source=%s ORDER BY dest
                """, (self.tkt.id,)):
            self.blocking.add(int(dest))
        self._old_blocking = copy.copy(self.blocking)

        self.blocked_by = set()
        for source, in self.env.db_query("""
                SELECT source FROM mastertickets WHERE dest=%s ORDER BY source
                """, (self.tkt.id,)):
            self.blocked_by.add(int(source))
        self._old_blocked_by = copy.copy(self.blocked_by)

    def save(self, author, comment='', when=None):
        """Save new links."""
        if when is None:
            when = datetime.datetime.now(utc)
        when_ts = to_utimestamp(when)

        new_blocking = set(int(n) for n in self.blocking)
        new_blocked_by = set(int(n) for n in self.blocked_by)

        to_check = [  # new, old, field
            (new_blocking, self._old_blocking, 'blockedby',
             ('source', 'dest')),
            (new_blocked_by, self._old_blocked_by, 'blocking',
             ('dest', 'source')),
        ]

        def append_id(lst):
            lst.append(str(self.tkt.id))

        def remove_id(lst):
            lst.remove(str(self.tkt.id))

        with self.env.db_transaction as db:
            for new_ids, old_ids, field, sourcedest in to_check:
                for n in new_ids | old_ids:
                    update_field = None
                    if n in new_ids and n not in old_ids:
                        # New ticket added
                        db("""INSERT INTO mastertickets (%s, %s)
                            VALUES (%%s, %%s)
                            """ % sourcedest, (self.tkt.id, n))
                        update_field = append_id
                    elif n not in new_ids and n in old_ids:
                        # Old ticket removed
                        db("""
                            DELETE FROM mastertickets WHERE %s=%%s AND %s=%%s
                            """ % sourcedest, (self.tkt.id, n))
                        update_field = remove_id

                    if update_field is not None:
                        old_value = None
                        ticket_custom_row_exists = False
                        for old_value, in db("""
                                SELECT value FROM ticket_custom
                                WHERE ticket=%s AND name=%s
                                """, (n, field)):
                            ticket_custom_row_exists = True
                            break
                        if old_value:
                            new_value = to_list(old_value)
                        else:
                            new_value = []
                        update_field(new_value)
                        new_value = ', '.join(sorted(new_value,
                                                     key=lambda x: int(x)))

                        # ticket, time and field must be unique for database
                        # integrity. The TicketImportPlugin assigns the same
                        # changetime to all ticket if not specified, which
                        # was causing an IntegrityError (#10194).
                        changelog = Ticket(self.env, n).get_changelog(when)
                        if any(field in cl for cl in changelog):
                            db("""UPDATE ticket_change
                                  SET author=%s, oldvalue=%s, newvalue=%s
                                  WHERE ticket=%s AND time=%s AND field=%s
                                  """, (author, old_value, new_value, n,
                                        when_ts, field))
                        else:
                            db("""INSERT INTO ticket_change
                                   (ticket, time, author, field,
                                    oldvalue, newvalue)
                                  VALUES (%s, %s, %s, %s, %s, %s)
                                  """, (n, when_ts, author, field,
                                        old_value, new_value))

                        # Add comment to referenced ticket if a comment
                        # hasn't already been added
                        if comment and \
                                not any('comment' in entry
                                        for entry
                                        in self.tkt.get_changelog(when)):
                            db("""INSERT INTO ticket_change
                                   (ticket, time, author, field,
                                    oldvalue, newvalue)
                                  VALUES (%s, %s, %s, %s, %s, %s)
                                  """, (n, when_ts, author, 'comment', '',
                                        '(In #%s) %s'
                                        % (self.tkt.id, comment)))

                        if ticket_custom_row_exists:
                            db("""UPDATE ticket_custom SET value=%s
                                  WHERE ticket=%s AND name=%s
                                  """, (new_value, n, field))
                        else:
                            db("""INSERT INTO ticket_custom
                                   (ticket, name, value)
                                  VALUES (%s, %s, %s)
                                  """, (n, field, new_value))

                        # Refresh the changetime to prevent concurrent edits.
                        db("UPDATE ticket SET changetime=%s WHERE id=%s",
                           (when_ts, n))

        # cursor.execute('DELETE FROM mastertickets
        #                'WHERE source=%s OR dest=%s',
        #                (self.tkt.id, self.tkt.id))
        # data = []
        # for tkt in self.blocking:
        #     if isinstance(tkt, Ticket):
        #         tkt = tkt.id
        #     data.append((self.tkt.id, tkt))
        # for tkt in self.blocked_by:
        #     if isinstance(tkt, Ticket):
        #         tkt = tkt.id
        #     data.append((tkt, self.tkt.id))
        #
        # cursor.executemany('INSERT INTO mastertickets (source, dest) '
        #                    'VALUES (%s, %s)', data)

    def __nonzero__(self):
        return bool(self.blocking) or bool(self.blocked_by)

    def __repr__(self):
        def l(arr):
            arr2 = []
            for tkt in arr:
                if isinstance(tkt, Ticket):
                    tkt = tkt.id
                arr2.append(str(tkt))
            return '[%s]' % ','.join(arr2)

        return '<mastertickets.model.TicketLinks #%s ' \
               'blocking=%s blocked_by=%s>' % \
               (self.tkt.id, l(getattr(self, 'blocking', [])),
                l(getattr(self, 'blocked_by', [])))

    @staticmethod
    def walk_tickets(env, tkt_ids, full=False):
        """Return an iterable of all links reachable directly above or
        below those ones.
        """

        def visit(tkt, memo, next_fn):
            if tkt in memo:
                return False

            links = TicketLinks(env, tkt)
            memo[tkt] = links

            for n in next_fn(links):
                visit(n, memo, next_fn)

        memo1 = {}
        memo2 = {}
        for tid in tkt_ids:
            if full:
                visit(tid, memo1, lambda links: links.blocking |
                                               links.blocked_by)
            else:
                visit(tid, memo1, lambda links: links.blocking)
                visit(tid, memo2, lambda links: links.blocked_by)
        memo1.update(memo2)
        return memo1.itervalues()
