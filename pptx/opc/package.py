# encoding: utf-8

"""Fundamental Open Packaging Convention (OPC) objects.

The :mod:`pptx.packaging` module coheres around the concerns of reading and writing
presentations to and from a .pptx file.
"""

import collections

from pptx.compat import is_string, Mapping
from pptx.opc.constants import RELATIONSHIP_TARGET_MODE as RTM, RELATIONSHIP_TYPE as RT
from pptx.opc.oxml import CT_Relationships, serialize_part_xml
from pptx.opc.packuri import PACKAGE_URI, PackURI
from pptx.opc.serialized import PackageReader, PackageWriter
from pptx.oxml import parse_xml
from pptx.util import lazyproperty


class OpcPackage(object):
    """Main API class for |python-opc|.

    A new instance is constructed by calling the :meth:`open` classmethod with a path
    to a package file or file-like object containing a package (.pptx file).
    """

    def __init__(self, pkg_file):
        self._pkg_file = pkg_file

    @classmethod
    def open(cls, pkg_file):
        """Return an |OpcPackage| instance loaded with the contents of `pkg_file`."""
        return cls(pkg_file)._load()

    def iter_parts(self):
        """Generate exactly one reference to each part in the package."""
        visited = set()
        for rel in self.iter_rels():
            if rel.is_external:
                continue
            part = rel.target_part
            if part in visited:
                continue
            yield part
            visited.add(part)

    def iter_rels(self):
        """Generate exactly one reference to each relationship in package.

        Performs a depth-first traversal of the rels graph.
        """
        visited = set()

        def walk_rels(rels):
            for rel in rels:
                yield rel
                # --- external items can have no relationships ---
                if rel.is_external:
                    continue
                # --- all relationships other than those for the package belong to a
                # --- part. Once that part has been processed, processing it again
                # --- would lead to the same relationships appearing more than once.
                part = rel.target_part
                if part in visited:
                    continue
                visited.add(part)
                # --- recurse into relationships of each unvisited target-part ---
                for rel in walk_rels(part.rels):
                    yield rel

        for rel in walk_rels(self._rels):
            yield rel

    def load_rel(self, reltype, target, rId, is_external=False):
        """
        Return newly added |_Relationship| instance of *reltype* between this
        part and *target* with key *rId*. Target mode is set to
        ``RTM.EXTERNAL`` if *is_external* is |True|. Intended for use during
        load from a serialized package, where the rId is well known. Other
        methods exist for adding a new relationship to the package during
        processing.
        """
        return self._rels.add_relationship(reltype, target, rId, is_external)

    @property
    def main_document_part(self):
        """Return |Part| subtype serving as the main document part for this package.

        In this case it will be a |Presentation| part.
        """
        return self.part_related_by(RT.OFFICE_DOCUMENT)

    def next_partname(self, tmpl):
        """Return |PackURI| next available partname matching `tmpl`.

        `tmpl` is a printf (%)-style template string containing a single replacement
        item, a '%d' to be used to insert the integer portion of the partname.
        Example: '/ppt/slides/slide%d.xml'
        """
        # --- expected next partname is tmpl % n where n is one greater than the number
        # --- of existing partnames that match tmpl. Speed up finding the next one
        # --- (maybe) by searching from the end downward rather than from 1 upward.
        prefix = tmpl[: (tmpl % 42).find("42")]
        partnames = set(
            p.partname for p in self.iter_parts() if p.partname.startswith(prefix)
        )
        for n in range(len(partnames) + 1, 0, -1):
            candidate_partname = tmpl % n
            if candidate_partname not in partnames:
                return PackURI(candidate_partname)
        raise Exception("ProgrammingError: ran out of candidate_partnames")

    def part_related_by(self, reltype):
        """Return (single) part having relationship to this package of `reltype`.

        Raises |KeyError| if no such relationship is found and |ValueError| if more than
        one such relationship is found.
        """
        return self._rels.part_with_reltype(reltype)

    def relate_to(self, target, reltype, is_external=False):
        """Return rId key of relationship of `reltype` to `target`.

        If such a relationship already exists, its rId is returned. Otherwise the
        relationship is added and its new rId returned.
        """
        if is_external:
            return self._rels.get_or_add_ext_rel(reltype, target)
        else:
            return self._rels.get_or_add(reltype, target)

    def save(self, pkg_file):
        """Save this package to `pkg_file`.

        `pkg_file` can be either a path to a file (a string) or a file-like object.
        """
        PackageWriter.write(pkg_file, self._rels, tuple(self.iter_parts()))

    def _load(self):
        """Return the package after loading all parts and relationships."""
        pkg_xml_rels, parts = _PackageLoader.load(self._pkg_file, self)
        self._rels.load_from_xml(PACKAGE_URI, pkg_xml_rels, parts)
        return self

    @lazyproperty
    def _rels(self):
        """The |_Relationships| object containing the relationships for this package."""
        return _Relationships(PACKAGE_URI.baseURI)


class _PackageLoader(object):
    """Function-object that loads a package from disk (or other store)."""

    def __init__(self, pkg_file, package):
        self._pkg_file = pkg_file
        self._package = package

    @classmethod
    def load(cls, pkg_file, package):
        """Return (pkg_xml_rels, parts) pair resulting from loading `pkg_file`.

        The returned `parts` value is a {partname: part} mapping with each part in the
        package included and constructed complete with its relationships to other parts
        in the package.

        The returned `pkg_xml_rels` value is a `CT_Relationships` object containing the
        parsed package relationships. It is the caller's responsibility (the package
        object) to load those relationships into its |_Relationships| object.
        """
        return cls(pkg_file, package)._load()

    def _load(self):
        """Return (pkg_xml_rels, parts) pair resulting from loading pkg_file."""
        # --- ugly temporary hack to make this interim `._load()` method produce the
        # --- same result as the one that's coming a few commits later.
        package = self._package
        Unmarshaller.unmarshal(self._package_reader, package, PartFactory)

        pkg_xml_rels = parse_xml(
            self._package_reader.rels_xml_for(self._pkg_file, PACKAGE_URI)
        )

        return pkg_xml_rels, {p.partname: p for p in package.iter_parts()}

    @lazyproperty
    def _package_reader(self):
        """|PackageReader| object providing access to package-items in pkg_file."""
        return PackageReader.from_file(self._pkg_file)


class Part(object):
    """Base class for package parts.

    Provides common properties and methods, but intended to be subclassed in client code
    to implement specific part behaviors. Also serves as the default class for parts
    that are not yet given specific behaviors.
    """

    def __init__(self, partname, content_type, blob=None, package=None):
        super(Part, self).__init__()
        self._partname = partname
        self._content_type = content_type
        self._blob = blob
        self._package = package

    @classmethod
    def load(cls, partname, content_type, blob, package):
        """Return `cls` instance loaded from arguments.

        This one is a straight pass-through, but subtypes may do some pre-processing,
        see XmlPart for an example.
        """
        return cls(partname, content_type, blob, package)

    @property
    def blob(self):
        """Contents of this package part as a sequence of bytes.

        May be text (XML generally) or binary. Intended to be overridden by subclasses.
        Default behavior is to return the blob initial loaded during `Package.open()`
        operation.
        """
        return self._blob

    @blob.setter
    def blob(self, bytes_):
        """Note that not all subclasses use the part blob as their blob source.

        In particular, the |XmlPart| subclass uses its `self._element` to serialize a
        blob on demand. This works fine for binary parts though.
        """
        self._blob = bytes_

    @property
    def content_type(self):
        """Content-type (MIME-type) of this part."""
        return self._content_type

    def drop_rel(self, rId):
        """Remove relationship identified by `rId` if its reference count is under 2.

        Relationships with a reference count of 0 are implicit relationships. Note that
        only XML parts can drop relationships.
        """
        if self._rel_ref_count(rId) < 2:
            self._rels.pop(rId)

    def load_rel(self, reltype, target, rId, is_external=False):
        """
        Return newly added |_Relationship| instance of *reltype* between this
        part and *target* with key *rId*. Target mode is set to
        ``RTM.EXTERNAL`` if *is_external* is |True|. Intended for use during
        load from a serialized package, where the rId is well known. Other
        methods exist for adding a new relationship to a part when
        manipulating a part.
        """
        return self._rels.add_relationship(reltype, target, rId, is_external)

    @property
    def package(self):
        """|OpcPackage| instance this part belongs to."""
        return self._package

    def part_related_by(self, reltype):
        """Return (single) part having relationship to this part of `reltype`.

        Raises |KeyError| if no such relationship is found and |ValueError| if more than
        one such relationship is found.
        """
        return self._rels.part_with_reltype(reltype)

    @property
    def partname(self):
        """|PackURI| partname for this part, e.g. "/ppt/slides/slide1.xml"."""
        return self._partname

    @partname.setter
    def partname(self, partname):
        if not isinstance(partname, PackURI):
            tmpl = "partname must be instance of PackURI, got '%s'"
            raise TypeError(tmpl % type(partname).__name__)
        self._partname = partname

    def relate_to(self, target, reltype, is_external=False):
        """Return rId key of relationship of `reltype` to `target`.

        If such a relationship already exists, its rId is returned. Otherwise the
        relationship is added and its new rId returned.
        """
        return (
            self._rels.get_or_add_ext_rel(reltype, target)
            if is_external
            else self._rels.get_or_add(reltype, target)
        )

    def related_part(self, rId):
        """Return related |Part| subtype identified by `rId`."""
        return self._rels[rId].target_part

    @lazyproperty
    def rels(self):
        """|Relationships| collection of relationships from this part to other parts."""
        # --- this must be public to allow the part graph to be traversed ---
        return self._rels

    def target_ref(self, rId):
        """Return URL contained in target ref of relationship identified by `rId`."""
        return self._rels[rId].target_ref

    def _blob_from_file(self, file):
        """Return bytes of `file`, which is either a str path or a file-like object."""
        # --- a str `file` is assumed to be a path ---
        if is_string(file):
            with open(file, "rb") as f:
                return f.read()

        # --- otherwise, assume `file` is a file-like object
        # --- reposition file cursor if it has one
        if callable(getattr(file, "seek")):
            file.seek(0)
        return file.read()

    def _rel_ref_count(self, rId):
        """Return int count of references in this part's XML to `rId`."""
        rIds = self._element.xpath("//@r:id")
        return len([_rId for _rId in rIds if _rId == rId])

    @lazyproperty
    def _rels(self):
        """|Relationships| collection of relationships from this part to other parts."""
        return _Relationships(self._partname.baseURI)


class XmlPart(Part):
    """Base class for package parts containing an XML payload, which is most of them.

    Provides additional methods to the |Part| base class that take care of parsing and
    reserializing the XML payload and managing relationships to other parts.
    """

    def __init__(self, partname, content_type, element, package=None):
        super(XmlPart, self).__init__(partname, content_type, package=package)
        self._element = element

    @classmethod
    def load(cls, partname, content_type, blob, package):
        """Return instance of `cls` loaded with parsed XML from `blob`."""
        element = parse_xml(blob)
        return cls(partname, content_type, element, package)

    @property
    def blob(self):
        """bytes XML serialization of this part."""
        return serialize_part_xml(self._element)

    @property
    def part(self):
        """This part.

        This is part of the parent protocol, "children" of the document will not know
        the part that contains them so must ask their parent object. That chain of
        delegation ends here for child objects.
        """
        return self


class PartFactory(object):
    """Constructs a registered subtype of |Part|.

    Client code can register a subclass of |Part| to be used for a package blob based on
    its content type.
    """

    part_type_for = {}
    default_part_type = Part

    def __new__(cls, partname, content_type, blob, package):
        PartClass = cls._part_cls_for(content_type)
        return PartClass.load(partname, content_type, blob, package)

    @classmethod
    def _part_cls_for(cls, content_type):
        """Return the custom part class registered for `content_type`.

        Returns |Part| if no custom class is registered for `content_type`.
        """
        if content_type in cls.part_type_for:
            return cls.part_type_for[content_type]
        return cls.default_part_type


class _Relationships(Mapping):
    """Collection of |_Relationship| instances, largely having dict semantics.

    Relationships are keyed by their rId, but may also be found in other ways, such as
    by their relationship type. `rels` is a dict of |Relationship| objects keyed by
    their rId.

    Note that iterating this collection generates |Relationship| references (values),
    not rIds (keys) as it would for a dict.
    """

    def __init__(self, base_uri):
        self._base_uri = base_uri

    def __contains__(self, rId):
        """Implement 'in' operation, like `"rId7" in relationships`."""
        return rId in self._rels

    def __getitem__(self, rId):
        """Implement relationship lookup by rId using indexed access, like rels[rId]."""
        try:
            return self._rels[rId]
        except KeyError:
            raise KeyError("no relationship with key '%s'" % rId)

    def __iter__(self):
        """Implement iteration of relationships."""
        return iter(list(self._rels.values()))

    def __len__(self):
        """Return count of relationships in collection."""
        return len(self._rels)

    def add_relationship(self, reltype, target, rId, is_external=False):
        """Return a newly added |_Relationship| instance."""
        rel = _Relationship(
            self._base_uri,
            rId,
            reltype,
            RTM.EXTERNAL if is_external else RTM.INTERNAL,
            target,
        )
        self._rels[rId] = rel
        return rel

    def get_or_add(self, reltype, target_part):
        """Return str rId of `reltype` to `target_part`.

        The rId of an existing matching relationship is used if present. Otherwise, a
        new relationship is added and that rId is returned.
        """
        existing_rId = self._get_matching(reltype, target_part)
        return (
            self._add_relationship(reltype, target_part)
            if existing_rId is None
            else existing_rId
        )

    def get_or_add_ext_rel(self, reltype, target_ref):
        """Return str rId of external relationship of `reltype` to `target_ref`.

        The rId of an existing matching relationship is used if present. Otherwise, a
        new relationship is added and that rId is returned.
        """
        existing_rId = self._get_matching(reltype, target_ref, is_external=True)
        return (
            self._add_relationship(reltype, target_ref, is_external=True)
            if existing_rId is None
            else existing_rId
        )

    def load_from_xml(self, base_uri, xml_rels, parts):
        """Replace any relationships in this collection with those from `xml_rels`."""

        def iter_valid_rels():
            """Filter out broken relationships such as those pointing to NULL."""
            for rel_elm in xml_rels.relationship_lst:
                # --- Occasionally a PowerPoint plugin or other client will "remove"
                # --- a relationship simply by "voiding" its Target value, like making
                # --- it "/ppt/slides/NULL". Skip any relationships linking to a
                # --- partname that is not present in the package.
                if rel_elm.targetMode == RTM.INTERNAL:
                    partname = PackURI.from_rel_ref(base_uri, rel_elm.target_ref)
                    if partname not in parts:
                        continue
                yield _Relationship.from_xml(base_uri, rel_elm, parts)

        self._rels.clear()
        self._rels.update((rel.rId, rel) for rel in iter_valid_rels())

    def part_with_reltype(self, reltype):
        """Return target part of relationship with matching `reltype`.

        Raises |KeyError| if not found and |ValueError| if more than one matching
        relationship is found.
        """
        rels_of_reltype = self._rels_by_reltype[reltype]

        if len(rels_of_reltype) == 0:
            raise KeyError("no relationship of type '%s' in collection" % reltype)

        if len(rels_of_reltype) > 1:
            raise ValueError(
                "multiple relationships of type '%s' in collection" % reltype
            )

        return rels_of_reltype[0].target_part

    def pop(self, rId):
        """Return |Relationship| identified by `rId` after removing it from collection.

        The caller is responsible for ensuring it is no longer required.
        """
        return self._rels.pop(rId)

    @property
    def xml(self):
        """bytes XML serialization of this relationship collection.

        This value is suitable for storage as a .rels file in an OPC package. Includes
        a `<?xml` header with encoding as UTF-8.
        """
        rels_elm = CT_Relationships.new()
        for rel in self:
            rels_elm.add_rel(rel.rId, rel.reltype, rel.target_ref, rel.is_external)
        return rels_elm.xml

    def _add_relationship(self, reltype, target, is_external=False):
        """Return str rId of |_Relationship| newly added to spec."""
        rId = self._next_rId
        self._rels[rId] = _Relationship(
            self._base_uri,
            rId,
            reltype,
            target_mode=RTM.EXTERNAL if is_external else RTM.INTERNAL,
            target=target,
        )
        return rId

    def _get_matching(self, reltype, target, is_external=False):
        """Return optional str rId of rel of `reltype`, `target`, and `is_external`.

        Returns `None` on no matching relationship
        """
        for rel in self._rels_by_reltype[reltype]:
            if rel.is_external != is_external:
                continue
            rel_target = rel.target_ref if rel.is_external else rel.target_part
            if rel_target != target:
                continue
            return rel.rId

        return None

    @property
    def _next_rId(self):
        """Next str rId available in collection.

        The next rId is the first unused key starting from "rId1" and making use of any
        gaps in numbering, e.g. 'rId2' for rIds ['rId1', 'rId3'].
        """
        # --- The common case is where all sequential numbers starting at "rId1" are
        # --- used and the next available rId is "rId%d" % (len(rels)+1). So we start
        # --- there and count down to produce the best performance.
        for n in range(len(self) + 1, 0, -1):
            rId_candidate = "rId%d" % n  # like 'rId19'
            if rId_candidate not in self._rels:
                return rId_candidate

    @lazyproperty
    def _rels(self):
        """dict {rId: _Relationship} containing relationships of this collection."""
        return dict()

    @property
    def _rels_by_reltype(self):
        """defaultdict {reltype: [rels]} for all relationships in collection."""
        D = collections.defaultdict(list)
        for rel in self:
            D[rel.reltype].append(rel)
        return D


class Unmarshaller(object):
    """
    Hosts static methods for unmarshalling a package from a |PackageReader|
    instance.
    """

    @staticmethod
    def unmarshal(pkg_reader, package, part_factory):
        """
        Construct graph of parts and realized relationships based on the
        contents of *pkg_reader*, delegating construction of each part to
        *part_factory*. Package relationships are added to *pkg*.
        """
        parts = Unmarshaller._unmarshal_parts(pkg_reader, package, part_factory)
        Unmarshaller._unmarshal_relationships(pkg_reader, package, parts)

    @staticmethod
    def _unmarshal_parts(pkg_reader, package, part_factory):
        """
        Return a dictionary of |Part| instances unmarshalled from
        *pkg_reader*, keyed by partname. Side-effect is that each part in
        *pkg_reader* is constructed using *part_factory*.
        """
        parts = {}
        for partname, content_type, blob in pkg_reader.iter_sparts():
            parts[partname] = part_factory(partname, content_type, blob, package)
        return parts

    @staticmethod
    def _unmarshal_relationships(pkg_reader, package, parts):
        """
        Add a relationship to the source object corresponding to each of the
        relationships in *pkg_reader* with its target_part set to the actual
        target part in *parts*.
        """
        for source_uri, srel in pkg_reader.iter_srels():
            source = package if source_uri == "/" else parts[source_uri]
            target = (
                srel.target_ref if srel.is_external else parts[srel.target_partname]
            )
            source.load_rel(srel.reltype, target, srel.rId, srel.is_external)


class _Relationship(object):
    """Value object describing link from a part or package to another part."""

    def __init__(self, base_uri, rId, reltype, target_mode, target):
        self._base_uri = base_uri
        self._rId = rId
        self._reltype = reltype
        self._target_mode = target_mode
        self._target = target

    @classmethod
    def from_xml(cls, base_uri, rel, parts):
        """Return |_Relationship| object based on CT_Relationship element `rel`."""
        target = (
            rel.target_ref
            if rel.targetMode == RTM.EXTERNAL
            else parts[PackURI.from_rel_ref(base_uri, rel.target_ref)]
        )
        return cls(base_uri, rel.rId, rel.reltype, rel.targetMode, target)

    @lazyproperty
    def is_external(self):
        """True if target_mode is `RTM.EXTERNAL`.

        An external relationship is a link to a resource outside the package, such as
        a web-resource (URL).
        """
        return self._target_mode == RTM.EXTERNAL

    @lazyproperty
    def reltype(self):
        """Member of RELATIONSHIP_TYPE describing relationship of target to source."""
        return self._reltype

    @lazyproperty
    def rId(self):
        """str relationship-id, like 'rId9'.

        Corresponds to the `Id` attribute on the `CT_Relationship` element and
        uniquely identifies this relationship within its peers for the source-part or
        package.
        """
        return self._rId

    @lazyproperty
    def target_part(self):
        """|Part| or subtype referred to by this relationship."""
        if self.is_external:
            raise ValueError(
                "`.target_part` property on _Relationship is undefined when "
                "target-mode is external"
            )
        return self._target

    @lazyproperty
    def target_partname(self):
        """|PackURI| instance containing partname targeted by this relationship.

        Raises `ValueError` on reference if target_mode is external. Use
        :attr:`target_mode` to check before referencing.
        """
        if self.is_external:
            raise ValueError(
                "`.target_partname` property on _Relationship is undefined when "
                "target-mode is external"
            )
        return self._target.partname

    @lazyproperty
    def target_ref(self):
        """str reference to relationship target.

        For internal relationships this is the relative partname, suitable for
        serialization purposes. For an external relationship it is typically a URL.
        """
        return (
            self._target
            if self.is_external
            else self.target_partname.relative_ref(self._base_uri)
        )
