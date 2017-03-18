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

import re

from trac.core import Component, implements
from trac.db import DatabaseManager
from trac.env import IEnvironmentSetupParticipant
from trac.ticket.api import ITicketChangeListener, ITicketManipulator
from trac.ticket.model import Ticket

from mastertickets import compat
from mastertickets import db_default
from mastertickets.model import TicketLinks


class MasterTicketsSystem(Component):
    """Central functionality for the MasterTickets plugin."""

    implements(IEnvironmentSetupParticipant, ITicketChangeListener,
               ITicketManipulator)

    NUMBERS_RE = re.compile(r'\d+', re.U)

    # IEnvironmentSetupParticipant methods

    def environment_created(self):
        with self.env.db_transaction as db:
            self.upgrade_environment(db)

    def environment_needs_upgrade(self, db):
        dbm = DatabaseManager(self.env)
        return dbm.needs_upgrade(db_default.version, db_default.name) or \
               self._ticket_custom_needs_upgrade()

    def upgrade_environment(self, db):
        dbm = DatabaseManager(self.env)
        if dbm.needs_upgrade(db_default.version, db_default.name):
            if not dbm.get_database_version(db_default.name):
                dbm.create_tables(db_default.tables)
                dbm.set_database_version(db_default.version, db_default.name)
            else:
                dbm.upgrade(db_default.version, db_default.name,
                            'mastertickets.upgrades')

        custom = self.config['ticket-custom']
        save_config = False
        if 'blocking' not in custom:
            custom.set('blocking', 'text')
            custom.set('blocking.label', 'Blocking')
            save_config = True
        if 'blockedby' not in custom:
            custom.set('blockedby', 'text')
            custom.set('blockedby.label', 'Blocked By')
            save_config = True
        if save_config:
            self.config.save()

    # ITicketChangeListener methods

    def ticket_created(self, tkt):
        self.ticket_changed(tkt, '', tkt['reporter'], {})

    def ticket_changed(self, tkt, comment, author, old_values):
        links = self._prepare_links(tkt)
        links.save(author, comment, tkt.time_changed)

    def ticket_deleted(self, tkt):
        links = TicketLinks(self.env, tkt)
        links.blocking = set()
        links.blocked_by = set()
        links.save('trac', "Ticket #%s deleted" % tkt.id)

    # ITicketManipulator methods

    def prepare_ticket(self, req, ticket, fields, actions):
        pass

    def validate_ticket(self, req, ticket):
        tid = ticket.id
        links = self._prepare_links(ticket)

        if req.args.get('action') == 'resolve' and \
                req.args.get('action_resolve_resolve_resolution') == 'fixed':
            for i in links.blocked_by:
                if Ticket(self.env, i)['status'] != 'closed':
                    yield None, "Ticket #%s is blocking this ticket" % i

        # Check that ticket does not have itself as a blocker
        if tid in links.blocking | links.blocked_by:
            yield 'blocked_by', "This ticket is blocking itself"
            return

        # Check that there aren't any blocked_by in blocking or their parents
        blocking = links.blocking.copy()
        while len(blocking) > 0:
            if len(links.blocked_by & blocking) > 0:
                yield 'blocked_by', "This ticket has circular dependencies"
                return
            new_blocking = set()
            for link in blocking:
                tmp_tkt = Ticket(self.env, link)
                new_blocking |= TicketLinks(self.env, tmp_tkt).blocking
            blocking = new_blocking

        for field in ('blocking', 'blockedby'):
            try:
                ids = self.NUMBERS_RE.findall(ticket[field] or '')
                for tid in ids[:]:
                    for _ in self.env.db_query("""
                            SELECT id FROM ticket WHERE id=%s
                            """, (tid,)):
                        break
                    else:
                        ids.remove(tid)
                ticket[field] = ', '.join(sorted(ids, key=lambda x: int(x)))
            except Exception, e:
                self.log.debug("MasterTickets: Error parsing %s \"%s\": %s",
                               field, ticket[field], e)
                yield field, "Not a valid list of ticket IDs"

    # Internal methods

    def _prepare_links(self, tkt):
        links = TicketLinks(self.env, tkt)
        links.blocking = set(int(n) for n in self.NUMBERS_RE.findall(tkt['blocking'] or ''))
        links.blocked_by = set(int(n) for n in self.NUMBERS_RE.findall(tkt['blockedby'] or ''))
        return links

    def _ticket_custom_needs_upgrade(self):
        return 'blocking' not in self.config['ticket-custom'] or \
               'blockedby' not in self.config['ticket-custom']
