"""
KOI Knowledge Graph - Ontology Namespace Constants

Defines standard namespace prefixes used throughout the KG extraction system.
These align with the op-v1.1-base.ttl ontology definitions.
"""

# Standard ontology namespaces
SCHEMA = "http://schema.org/"
PROV = "http://www.w3.org/ns/prov#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"

# Regen Network custom namespaces
REG = "https://regen.network/ontology#"
REGX = "https://regen.network/ontology/experimental#"

# Namespace dictionary for RDF serialization
NAMESPACES = {
    "schema": SCHEMA,
    "prov": PROV,
    "skos": SKOS,
    "rdf": RDF,
    "rdfs": RDFS,
    "xsd": XSD,
    "reg": REG,
    "regx": REGX
}
