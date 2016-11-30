
from pptx.oxml import parse_xml
from pptx.oxml.xmlchemy import (
        BaseOxmlElement, OneAndOnlyOne, ZeroOrMore, ZeroOrOne,
        OptionalAttribute, RequiredAttribute
)
from pptx.oxml.simpletypes import (
        ST_PositiveCoordinate,
)
from pptx.oxml.ns import nsdecls

class CT_CustomGeometry2D(BaseOxmlElement):
    """

    """
    pathLst = OneAndOnlyOne('a:pathLst')

class CT_Path2DList(BaseOxmlElement):
    """

    """
    path = ZeroOrMore('a:path')

class CT_Path2D(BaseOxmlElement):
    """

    """
    moveTo = ZeroOrMore('a:moveTo')
    lnTo   = ZeroOrMore('a:lnTo')
    close  = ZeroOrMore('a:close')

    w = RequiredAttribute('w', ST_PositiveCoordinate)
    h = RequiredAttribute('h', ST_PositiveCoordinate)

    def add_moveTo(self, x, y):
        """
        Create a moveTo element to the provided x and y
        points, specified in pptx.Length units.
        """
        mt = self._add_moveTo()
        mt.pt.x = x
        mt.pt.y = y
        return mt

    def add_lnTo(self, x, y):
        """
        Create a lineTo element to the provided x and y
        points, specified in pptx.Length units.
        """
        lt = self._add_lnTo()
        lt.pt.x = x
        lt.pt.y = y
        return lt

    def _new_moveTo(self):
        return CT_Path2DMoveTo.new()

    def _new_lnTo(self):
        return CT_Path2DLineTo.new()

class CT_Path2DMoveTo(BaseOxmlElement):
    """

    """
    pt = OneAndOnlyOne('a:pt')

    @classmethod
    def new(cls):
        xml = cls._tmpl()
        moveTo = parse_xml(xml)
        return moveTo

    @classmethod
    def _tmpl(self):
        return (
                '<a:moveTo %s>\n'
                '   <a:pt x="%s" y="%s" />\n'
                '</a:moveTo>'
        ) % (nsdecls('a'), '%d', '%d')

class CT_Path2DLineTo(BaseOxmlElement):
    """

    """
    pt = OneAndOnlyOne('a:pt')

    @classmethod
    def new(cls):
        xml = cls._tmpl()
        return parse_xml(xml)

    @classmethod
    def _tmpl(self):
        return (
                '<a:lnTo %s>\n'
                '   <a:pt x="%s" y="%s" />\n'
                '</a:lnTo>'
        ) % (nsdecls('a'), '%d', '%d')

class CT_Path2DClose(BaseOxmlElement):
    """

    """
    pass

class CT_AdjPoint2D(BaseOxmlElement):
    """

    """
    x = RequiredAttribute('x', ST_PositiveCoordinate)
    y = RequiredAttribute('y', ST_PositiveCoordinate)
