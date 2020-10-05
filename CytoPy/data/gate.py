from .geometry import ThresholdGeom, PolygonGeom
import mongoengine


class ChildThreshold(mongoengine.EmbeddedDocument):
    """
    Child population of a Threshold gate

    Parameters
    -----------
    name: str
        Population name
    definition: str
        Definition of population e.g "+" or "-" for 1 dimensional gate or "++" etc for 2 dimensional gate
    geom: ThresholdGeom
        Geometric definition for this child population
    """
    name = mongoengine.StringField()
    definition = mongoengine.StringField()
    geom = mongoengine.EmbeddedDocumentField(ThresholdGeom)


class ChildPolygon(mongoengine.EmbeddedDocument):
    """
    Child population of a Polgon or Ellipse gate

    Parameters
    -----------
    name: str
        Population name
    geom: ThresholdGeom
        Geometric definition for this child population
    """
    name = mongoengine.StringField()
    geom = mongoengine.EmbeddedDocumentField(PolygonGeom)


class Gate(mongoengine.Document):
    """
    Base class for a Gate
    """
    gate_name = mongoengine.StringField(required=True)
    parent = mongoengine.StringField(required=True)
    x = mongoengine.StringField(required=True)
    y = mongoengine.StringField(required=False)
    preprocessing = mongoengine.DictField()
    postprocessing = mongoengine.DictField()
    method = mongoengine.StringField()
    method_kwargs = mongoengine.DictField()

    meta = {
        'db_alias': 'core',
        'collection': 'gates',
        'allow_inheritance': True
    }


class ThresholdGate(Gate):
    """
    A ThresholdGate is for density based gating that applies one or two-dimensional gates
    to data in the form of straight lines, parallel to the axis that fall in the area of minimum
    density.
    """
    children = mongoengine.EmbeddedDocumentListField(ChildThreshold)

    def add_child(self,
                  child: ChildThreshold):
        if self.y is not None:
            assert child.definition in ["++", "+-", "-+", "--"], "Invalid child definition, should be one of: '++', '+-', '-+', or '--'"
        else:
            assert child.definition in ["+", "-"], "Invalid child definition, should be either '+' or '-'"
        child.geom.x = self.x
        child.geom.y = self.y
        child.geom.transform_x, child.geom.transform_y = self.preprocessing.get("transform_x", None), self.preprocessing.get("transform_y", None)
        self.children.append(child)


class PolygonGate(Gate):
    """
    Polygon gates generate polygon shapes that capture populations of varying shapes. These can
    be generated by any number of clustering algorithms.
    """
    children = mongoengine.EmbeddedDocumentListField(ChildPolygon)


class EllipseGate(Gate):
    """
    Ellipse gates generate circular or elliptical gates and can be generated from algorithms that are
    centroid based (like K-means) or probabilistic methods that estimate the covariance matrix of one
    or more gaussian components such as mixture models.
    """
    children = mongoengine.EmbeddedDocumentListField(ChildPolygon)
