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

import functools
import graphviz
import os
import re
import subprocess

from trac.config import BoolOption, ChoiceOption, ListOption, Option
from trac.core import Component, TracError, implements
from trac.resource import ResourceNotFound, get_resource_summary
from trac.ticket.model import Ticket
from trac.ticket.query import Query
from trac.util import as_int, escape, to_unicode
from trac.util.html import html
from trac.util.presentation import classes
from trac.util.translation import _, tag_
from trac.web.api import IRequestFilter, IRequestHandler, \
                         ITemplateStreamFilter
from trac.web.chrome import ITemplateProvider, add_ctxtnav, add_script

from model import TicketLinks


class MasterTicketsModule(Component):
    """Provides support for ticket dependencies."""

    implements(IRequestFilter, IRequestHandler, ITemplateProvider,
               ITemplateStreamFilter)

    dot_path = Option('mastertickets', 'dot_path', default='dot',
        doc="Path to the dot executable.")

    gs_path = Option('mastertickets', 'gs_path', default='gs',
        doc="Path to the ghostscript executable.")

    use_gs = BoolOption('mastertickets', 'use_gs', default=False,
        doc="If enabled, use ghostscript to produce nicer output.")

    acceptable_formats = ListOption('mastertickets', 'acceptable_formats',
                                    default='png,cmapx', sep=',',
        doc="""The formats that may be chosen; execute dot -T? for a
            list of options.""")

    closed_color = Option('mastertickets', 'closed_color', default='green',
        doc="Color of closed tickets")

    opened_color = Option('mastertickets', 'opened_color', default='red',
        doc="Color of opened tickets")

    show_key = Option('mastertickets', 'show_key', default=False,
        doc="Show a key for open/closed nodes")

    closed_text = Option('mastertickets', 'closed_text', default='Done',
        doc="Text for key showing closed tickets")

    opened_text = Option('mastertickets', 'opened_text', default='ToDo',
        doc="Text for key showing opened tickets")

    highlight_target = Option('mastertickets', 'highlight_target',
                              default=False,
        doc="Highlight target tickets in graph")

    full_graph = Option('mastertickets', 'full_graph', default=False,
        doc="Show full dep. graph, not just direct blocking links")

    graph_direction = ChoiceOption('mastertickets', 'graph_direction',
                                   choices=['TD', 'LR', 'DT', 'RL'],
        doc="""Direction of the dependency graph (TD = Top Down,
            DT = Down Top, LR = Left Right, RL = Right Left).""")

    fields = set(['blocking', 'blockedby'])

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if template is not None:
            if req.path_info.startswith('/ticket/'):
                # In case of an invalid ticket, the data is invalid
                if not data:
                    return template, data, content_type
                tkt = data['ticket']
                links = TicketLinks(self.env, tkt)

                for i in links.blocked_by:
                    if Ticket(self.env, i)['status'] != 'closed':
                        add_script(req, 'mastertickets/js/disable_resolve.js')
                        break

                # Add link to depgraph if needed.
                if links:
                    add_ctxtnav(req, 'Depgraph',
                                req.href.depgraph('ticket', tkt.id))

                for change in data.get('changes', {}):
                    if 'fields' not in change:
                        continue
                    for field, field_data in change['fields'].iteritems():
                        if field in self.fields:
                            if field_data['new'].strip():
                                new = to_int_set(field_data['new'])
                            else:
                                new = set()
                            if field_data['old'].strip():
                                old = to_int_set(field_data['old'])
                            else:
                                old = set()
                            add = new - old
                            sub = old - new
                            elms = html()
                            if add:
                                elms.append(
                                    html.em(u', '.join(unicode(n)
                                                       for n in sorted(add)))
                                )
                                elms.append(u' added')
                            if add and sub:
                                elms.append(u'; ')
                            if sub:
                                elms.append(
                                    html.em(u', '.join(unicode(n)
                                                       for n in sorted(sub)))
                                )
                                elms.append(u' removed')
                            field_data['rendered'] = elms

            # Add a link to generate a dependency graph for all the tickets
            # in the milestone
            if req.path_info.startswith('/milestone/'):
                if not data:
                    return template, data, content_type
                milestone = data['milestone']
                add_ctxtnav(req, 'Depgraph',
                            req.href.depgraph('milestone', milestone.name))

        return template, data, content_type

    # ITemplateStreamFilter methods

    def filter_stream(self, req, method, filename, stream, data):
        if not data:
            return stream

        # Try all at the same time to catch changed or processed templates.
        if filename in ['report_view.html', 'query_results.html',
                        'ticket.html', 'query.html']:
            # For ticket.html
            if 'fields' in data and isinstance(data['fields'], list):
                for field in data['fields']:
                    for f in self.fields:
                        if field['name'] == f and data['ticket'][f]:
                            field['rendered'] = \
                                self._link_tickets(req, data['ticket'][f])
            # For query_results.html and query.html
            if 'groups' in data and isinstance(data['groups'], list):
                for group, tickets in data['groups']:
                    for ticket in tickets:
                        for f in self.fields:
                            if f in ticket:
                                ticket[f] = self._link_tickets(req, ticket[f])
            # For report_view.html
            if 'row_groups' in data and isinstance(data['row_groups'], list):
                for group, rows in data['row_groups']:
                    for row in rows:
                        if 'cell_groups' in row and \
                                isinstance(row['cell_groups'], list):
                            for cells in row['cell_groups']:
                                for cell in cells:
                                    # If the user names column in the report
                                    # differently (blockedby AS "blocked by")
                                    # then this will not find it
                                    if cell.get('header', {}).get('col') \
                                            in self.fields:
                                        cell['value'] = \
                                            self._link_tickets(req,
                                                               cell['value'])
        return stream

    # ITemplateProvider methods

    def get_htdocs_dirs(self):
        from pkg_resources import resource_filename
        return [('mastertickets', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        from pkg_resources import resource_filename
        return [resource_filename(__name__, 'templates')]

    # IRequestHandler methods

    def match_request(self, req):
        match = re.match(r'^/depgraph/(?P<realm>ticket|milestone)/'
                         r'(?P<id>((?!depgraph.png).)+)(/depgraph.png)?$',
                         req.path_info)
        if match:
            req.args['realm'] = match.group('realm')
            req.args['id'] = match.group('id')
            return True

    def process_request(self, req):
        realm = req.args['realm']
        id_ = req.args['id']

        if not which(self.dot_path):
            raise TracError(_("Path to dot executable is invalid: %(path)s",
                              path=self.dot_path))

        # Urls to generate the depgraph for a ticket is /depgraph/ticketnum
        # Urls to generate the depgraph for a milestone is
        # /depgraph/milestone/milestone_name

        # List of tickets to generate the depgraph.
        if realm == 'milestone':
            # We need to query the list of tickets in the milestone
            query = Query(self.env, constraints={'milestone': [id_]}, max=0)
            tkt_ids = [fields['id'] for fields in query.execute(req)]
        else:
            tid = as_int(id_, None)
            if tid is None:
                raise TracError(tag_("%(id)s is not a valid ticket id.",
                                     id=html.tt(id_)))
            tkt_ids = [tid]

        # The summary argument defines whether we place the ticket id or
        # its summary in the node's label
        label_summary = 0
        if 'summary' in req.args:
            label_summary = int(req.args.get('summary'))

        g = self._build_graph(req, tkt_ids, label_summary=label_summary)
        if req.path_info.endswith('/depgraph.png') or 'format' in req.args:
            format_ = req.args.get('format')
            if format_ == 'text':
                # In case g.__str__ returns unicode, convert it in ascii
                req.send(to_unicode(g).encode('ascii', 'replace'),
                         'text/plain')
            elif format_ == 'debug':
                import pprint

                req.send(
                    pprint.pformat(
                        [TicketLinks(self.env, tkt_id) for tkt_id in tkt_ids]
                    ),
                    'text/plain')
            elif format_ is not None:
                if format_ in self.acceptable_formats:
                    req.send(g.render(self.dot_path, format_), 'text/plain')
                else:
                    raise TracError(_("The %(format)s format is not allowed.",
                                      format=format_))

            if self.use_gs:
                ps = g.render(self.dot_path, 'ps2')
                gs = subprocess.Popen(
                    [self.gs_path, '-q', '-dTextAlphaBits=4',
                     '-dGraphicsAlphaBits=4', '-sDEVICE=png16m',
                     '-sOutputFile=%stdout%', '-'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
                img, err = gs.communicate(ps)
                if err:
                    self.log.debug('MasterTickets: Error from gs: %s', err)
            else:
                img = g.render(self.dot_path)
            req.send(img, 'image/png')
        else:
            data = {}

            # Add a context link to enable/disable labels in nodes.
            if label_summary:
                add_ctxtnav(req, 'Without labels',
                            req.href(req.path_info, summary=0))
            else:
                add_ctxtnav(req, 'With labels',
                            req.href(req.path_info, summary=1))

            if realm == 'milestone':
                add_ctxtnav(req, 'Back to Milestone: %s' % id_,
                            req.href.milestone(id_))
                data['milestone'] = id_
            else:
                data['ticket'] = id_
                add_ctxtnav(req, 'Back to Ticket #%s' % id_,
                            req.href.ticket(id_))
            data['graph'] = g
            data['graph_render'] = functools.partial(g.render, self.dot_path)
            data['use_gs'] = self.use_gs

            return 'depgraph.html', data, None

    def _build_graph(self, req, tkt_ids, label_summary=0):
        g = graphviz.Graph(log=self.log)
        g.label_summary = label_summary

        g.attributes['rankdir'] = self.graph_direction

        node_default = g['node']
        node_default['style'] = 'filled'

        edge_default = g['edge']
        edge_default['style'] = ''

        # Force this to the top of the graph
        for tid in tkt_ids:
            g[tid]

        if self.show_key:
            g[-1]['label'] = self.closed_text
            g[-1]['fillcolor'] = self.closed_color
            g[-1]['shape'] = 'box'
            g[-2]['label'] = self.opened_text
            g[-2]['fillcolor'] = self.opened_color
            g[-2]['shape'] = 'box'

        links = TicketLinks.walk_tickets(self.env, tkt_ids, self.full_graph)
        links = sorted(links, key=lambda link: link.tkt.id)
        for link in links:
            tkt = link.tkt
            node = g[tkt.id]
            if label_summary:
                node['label'] = u'#%s %s' % (tkt.id, tkt['summary'])
            else:
                node['label'] = u'#%s' % tkt.id
            node['fillcolor'] = tkt['status'] == 'closed' and \
                                self.closed_color or self.opened_color
            node['URL'] = req.href.ticket(tkt.id)
            node['alt'] = u'Ticket #%s' % tkt.id
            node['tooltip'] = escape(tkt['summary'])
            if self.highlight_target and tkt.id in tkt_ids:
                node['penwidth'] = 3

            for n in link.blocking:
                node > g[n]

        return g

    def _link_tickets(self, req, tickets):
        items = []

        for i, word in enumerate(re.split(r'([;,\s]+)', tickets)):
            if i % 2:
                items.append(word)
            elif word:
                tid = word
                word = '#%s' % word

                try:
                    ticket = Ticket(self.env, tid)
                    if 'TICKET_VIEW' in req.perm(ticket.resource):
                        word = \
                            html.a(
                                '#%s' % ticket.id,
                                href=req.href.ticket(ticket.id),
                                class_=classes(ticket['status'], 'ticket'),
                                title=get_resource_summary(self.env,
                                                           ticket.resource)
                            )
                except ResourceNotFound:
                    pass

                items.append(word)

        if items:
            return html(items)
        else:
            return None


def to_int_set(splittable):
    return set(int(n) for n in re.split(r'[\s,]+', splittable))


def which(program):

    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None
