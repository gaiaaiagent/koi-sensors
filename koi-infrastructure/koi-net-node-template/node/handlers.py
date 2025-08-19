import logging
from koi_net.processor.handler import HandlerType
from koi_net.processor.knowledge_object import KnowledgeObject
from koi_net.processor.interface import ProcessorInterface
from .core import node

logger = logging.getLogger(__name__)

"""
@node.processor.register_handler(
    handler_type=HandlerType.RID,
    rid_types=[]
)
def coordinator_contact(processor: ProcessorInterface, kobj: KnowledgeObject):
    ...
"""
