# encoding: utf-8

"""
Shared objects for unit data builder modules
"""

from __future__ import absolute_import, print_function, unicode_literals

from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls


class BaseBuilder(object):
    """
    Provides common behavior for all data builders.
    """

    def __init__(self):
        self._empty = False
        self._nsdecls = ""
        self._text = ""
        self._xmlattrs = []
        self._xmlattr_method_map = {}
        for attr_name in self.__attrs__:
            base_name = attr_name.split(":")[1] if ":" in attr_name else attr_name
            method_name = "with_%s" % base_name
            self._xmlattr_method_map[method_name] = attr_name
        self._child_bldrs = []

    def __getattr__(self, name):
        """
        Intercept attribute access to generalize "with_{xmlattr_name}()"
        methods.
        """
        if name in self._xmlattr_method_map:

            def with_xmlattr(value):
                xmlattr_name = self._xmlattr_method_map[name]
                self._set_xmlattr(xmlattr_name, value)
                return self

            return with_xmlattr

    @property
    def element(self):
        """
        Element parsed from XML generated by builder in current state
        """
        elm = parse_xml(self.xml())
        return elm

    def with_child(self, child_bldr):
        """
        Cause new child element specified by *child_bldr* to be appended to
        the children of this element.
        """
        self._child_bldrs.append(child_bldr)
        return self

    def with_nsdecls(self, *nspfxs):
        """
        Cause the element to contain namespace declarations. By default, the
        namespace prefixes defined in the Builder class are used. These can
        be overridden by providing exlicit prefixes, e.g.
        ``with_nsdecls('a', 'r')``.
        """
        if not nspfxs:
            nspfxs = self.__nspfxs__
        self._nsdecls = " %s" % nsdecls(*nspfxs)
        return self

    def xml(self, indent=0):
        """
        Return element XML based on attribute settings
        """
        indent_str = " " * indent
        if self._is_empty:
            xml = "%s%s\n" % (indent_str, self._empty_element_tag)
        else:
            xml = "%s\n" % self._non_empty_element_xml(indent)
        return xml

    @property
    def _empty_element_tag(self):
        return "<%s%s%s/>" % (self.__tag__, self._nsdecls, self._xmlattrs_str)

    @property
    def _end_tag(self):
        return "</%s>" % self.__tag__

    @property
    def _is_empty(self):
        return len(self._child_bldrs) == 0 and len(self._text) == 0

    def _non_empty_element_xml(self, indent):
        indent_str = " " * indent
        if self._text:
            xml = "%s%s%s%s" % (  # pragma: no cover
                indent_str,
                self._start_tag,
                self._text,
                self._end_tag,
            )
        else:
            xml = "%s%s\n" % (indent_str, self._start_tag)
            for child_bldr in self._child_bldrs:
                xml += child_bldr.xml(indent + 2)
            xml += "%s%s" % (indent_str, self._end_tag)
        return xml

    def _set_xmlattr(self, xmlattr_name, value):
        xmlattr_str = ' %s="%s"' % (xmlattr_name, str(value))
        self._xmlattrs.append(xmlattr_str)

    @property
    def _start_tag(self):
        return "<%s%s%s>" % (self.__tag__, self._nsdecls, self._xmlattrs_str)

    @property
    def _xmlattrs_str(self):
        """
        Return all element attributes as a string, like ' foo="bar" x="1"'.
        """
        return "".join(self._xmlattrs)
