# -*- Mode: Python -*-

# GDBus - GLib D-Bus Library
#
# Copyright (C) 2008-2011 Red Hat, Inc.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General
# Public License along with this library; if not, see <http://www.gnu.org/licenses/>.
#

import sys
import re

import config
import utils
import dbustypes
import parser

# ----------------------------------------------------------------------------------------------------

class MofCodeGenerator:
    def __init__(self, ifaces, moffile, interface_prefix, cim_prefix):
        self.ifaces = ifaces
        self.moffile = moffile
        self.interface_prefix = interface_prefix
        self.cim_prefix = cim_prefix

    def warning(self, msg):
        print >> sys.stderr, 'warning: ' + msg

    def signature_type(self, i, name, sig, annotations, level=0, full_sig=None, method_name=None):
        """Convert DBus signature to a CIM type"""
        if not full_sig:
            full_sig = sig

        inst = utils.lookup_annotation(annotations, 'CIMEmbeddedInstance')
        if inst:
            return ('string', '', ['EmbeddedInstance("%s")' % (inst), ])

        atype = utils.lookup_annotation(annotations, 'CIMType')
        if atype:
            return (atype, '', [])

        primitive_types = {
            'y': 'uint8',
            'b': 'boolean',
            'n': 'sint16',
            'q': 'uint16',
            'i': 'sint32',
            'u': 'uint32',
            'x': 'sint64',
            't': 'uint64',
            'd': 'real64',
            's': 'string',
            'o': 'CIM_ManagedElement REF ',
        }

        if not sig:
            self.warning("unknown type for '%s' ('%s'): %s" % (name, full_sig, sig))

        cimtype = primitive_types.get(sig, None)
        if cimtype:
            return (cimtype, '', []);

        if sig == 'a{sv}' and method_name:
            return('string', '', ['EmbeddedObject'])

        if sig[0] == 'a':
            (subtype, arr, quals) = self.signature_type(i, name, sig[1:], annotations, level + 1, full_sig);
            return (subtype, arr + '[]', quals)


        self.warning("cannot determine type of '%s' ('%s'): %s" % (name, full_sig, sig))
        return ('UNKNOWN', '', [])

    def classname(self, interface):
        cimclass = utils.lookup_annotation(interface.annotations, 'CIMClass')
        if cimclass:
            return cimclass
        cimclass = self.cim_prefix + interface.name_without_prefix[1:]
        cimclass = cimclass.replace('.', '')
        return cimclass

    def cimdoc(self, text, indent=1):
        remove_markup = re.compile(r' ?<[^>]*> ?')
        escape_quotes = re.compile(r'"')
        remove_newlines = re.compile(r'\n\s*')
        remove_empty_spaces_start = re.compile(r'^\s*')
        remove_empty_spaces_end = re.compile(r'\s*$')
        text = remove_markup.sub(' ', text)
        text = escape_quotes.sub('\\"', text)
        text = remove_newlines.sub('"\n' + (indent * 4) * ' ' + '" ', text)
        text = remove_empty_spaces_start.sub("", text)
        text = remove_empty_spaces_end.sub("", text)
        return '"' + text + '"'


    def handle_references(self):
        """
        1. Convert all 'o' and 'ao' properties (=object paths) into references.
        2. Convert all 'a{sv}' properties to setting objects.
        """
        for i in self.ifaces:
            i.refs = []
            i.settings = []
            removed = []
            for p in i.properties:
                if p.signature == 'o' or p.signature == 'ao' or utils.lookup_annotation(p.annotations, 'CIMAssociation'):
                    i.refs.append(p)
                    removed.append(p)
                if p.signature == 'a{sv}' or utils.lookup_annotation(p.annotations, 'CIMSetting'):
                    i.settings.append(p)
                    removed.append(p)
            i.properties = [p for p in i.properties if p not in removed]

    def print_method(self, i, m):
        if utils.lookup_annotation(m.annotations, 'CIMSkip') == '1':
            return
        self.print_qualifiers(m, indent=1)

        self.out.write(4 * " " + "int32 %s (\n" % (m.name))

        args = []
        indent = 8 * " "
        for arg in m.in_args:
            name = arg.name
            (_type, suffix, qualifiers) = self.signature_type(i, arg.name, arg.signature, arg.annotations, 2, method_name=m.name)
            q = self.render_qualifiers(arg, qualifiers + ['In'], 2)
            args.append((indent + "[%s]\n" + indent + "%s %s%s") % (", ".join(q), _type, name, suffix))
        for arg in m.out_args:
            name = arg.name
            (_type, suffix, qualifiers) = self.signature_type(i, arg.name, arg.signature, arg.annotations, 2, method_name=m.name)
            q = self.render_qualifiers(arg, qualifiers + ['In(false)', 'Out'], 2)
            args.append((indent + "[%s]\n" + indent + "%s %s%s") % (", ".join(q), _type, name, suffix))
        s = ",\n".join(args)
        self.out.write(s)

        self.out.write("\n" + (4 * " ") + ");\n")

    def print_property(self, i, p):
        if utils.lookup_annotation(p.annotations, 'CIMSkip') == '1':
            return
        if p.writable:
            self.warning("property '%s' is writable, no code is generated for it", p.name)
        self.print_qualifiers(p, indent=1)

        (cimtype, suffix, _qualifiers) = self.signature_type(i, p.name, p.signature, p.annotations)

        cimname = utils.lookup_annotation(p.annotations, 'CIMName')
        if not cimname:
            cimname = p.name

        self.out.write('    %s %s%s;\n' % (cimtype, cimname, suffix))
        self.out.write('\n')

    def print_reference(self, i, ref):
        if utils.lookup_annotation(ref.annotations, 'CIMSkip') == '1':
            return
        assoc_name = utils.lookup_annotation(ref.annotations, 'CIMAssociation')
        if not assoc_name:
            assoc_name = '%s%s' % (self.classname(i), ref.name)

        assoc_base = utils.lookup_annotation(ref.annotations, 'CIMAssociationBase')

        self.print_qualifiers(ref, ['Association'], 0)
        if assoc_base:
            self.out.write('class %s : %s  {\n' % (assoc_name, assoc_base))
        else:
            self.out.write('class %s {\n' % (assoc_name))

        local_name = utils.lookup_annotation(ref.annotations, 'CIMAssociationLocalName') or 'Antecedent'
        remote_name = utils.lookup_annotation(ref.annotations, 'CIMAssociationRemoteName') or 'Dependent'

        local_type = utils.lookup_annotation(ref.annotations, 'CIMAssociationLocalType') or self.classname(i)
        remote_type = utils.lookup_annotation(ref.annotations, 'CIMAssociationLocalType') or 'CIM_ManagedObject'
        self.out.write("    %s REF %s;\n" % (local_type, local_name))
        self.out.write("    %s REF %s;\n" % (remote_type, remote_name))

        self.out.write('}\n')

    def print_setting(self, i, setting):
        if utils.lookup_annotation(setting.annotations, 'CIMSkip') == '1':
            return

        classname = utils.lookup_annotation(setting.annotations, 'CIMSetting')
        if not classname:
            classname = '%sSettingData' % (self.classname(i))

        self.todo.write("// TODO: define following class:\n")
        self.print_qualifiers(setting, [], 0, stream=self.todo)
        self.todo.write('class %s : CIM_SettingData {\n' % (classname))
        self.todo.write('};\n')

        # generate just the association

        self.out.write("[Association]\n")

        j = len('SettingData')
        assoc_name = classname[:-j] + 'Element' + classname[-j:]
        self.out.write('class %s : CIM_ElementSettingData {\n' % (assoc_name))
        self.out.write("    %s REF ManagedElement;\n" % (self.classname(i)))
        self.out.write("    %s REF SettingData;\n" % (classname))
        self.out.write('}\n')


    def render_qualifiers(self, item, qualifiers=[], indent=1):
        quals = [q.encode('ascii') for q in qualifiers]
        try:
            if item.deprecated:
                quals.append('Deprecated')
        except AttributeError:
            pass
        if item.doc_string:
            quals.append('Description(%s)' % self.cimdoc(item.doc_string.encode('ascii'), indent + 1))
        return quals

    def print_qualifiers(self, item, qualifiers=[], indent=1, stream=None):
        if not stream:
            stream = self.out
        quals = self.render_qualifiers(item, qualifiers, indent)
        if quals:
            stream.write((indent * 4) * ' ' + '[' + ', '.join(quals) + ']\n')


    def generate(self):
        # self.out = open('%s.mof' % (self.moffile), 'w')
        self.out = sys.stdout
        self.todo = sys.stdout
        self.handle_references()
        for i in self.ifaces:
            self.print_qualifiers(i, indent=0)

            self.out.write('class %s {\n' % (self.classname(i)))

            for s in i.properties:
                self.print_property(i, s)

            for method in i.methods:
                self.print_method(i, method)

            self.out.write('};\n')
            self.out.write('\n');

            for ref in i.refs:
                self.print_reference(i, ref)

            for setting in i.settings:
                self.print_setting(i, setting)


            self.out.write('\n')
            self.out.write('// ---------------------------------------------\n')
            self.out.write('\n')

            continue

            if len(i.methods) > 0:
                self.out.write('<refsect1 role="details" id="gdbus-methods-%s">\n' % (i.name))
                self.out.write('  <title role="details.title">Method Details</title>\n' % ())
                for m in i.methods:
                    self.print_method(i, m)
                self.out.write('</refsect1>\n' % ())

            if len(i.signals) > 0:
                self.out.write('<refsect1 role="details" id="gdbus-signals-%s">\n' % (i.name))
                self.out.write('  <title role="details.title">Signal Details</title>\n' % ())
                for s in i.signals:
                    self.print_signal(i, s)
                self.out.write('</refsect1>\n' % ())

            self.out.write('</refentry>\n')
            self.out.write('\n')

