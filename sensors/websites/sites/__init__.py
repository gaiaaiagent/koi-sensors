"""
Site-specific modules for website sensor
"""

from .base_site import BaseSite
from .regentokenomics import RegentokenomicsSite
from .regen_network import RegenNetworkSite
from .forum_regen import ForumRegenSite
from .regen_foundation import RegenFoundationSite

# Registry of all site handlers
SITE_HANDLERS = {
    'regentokenomics.org': RegentokenomicsSite,
    'regen.network': RegenNetworkSite,
    'forum.regen.network': ForumRegenSite,
    'www.regen.foundation': RegenFoundationSite,
    'regen.foundation': RegenFoundationSite,
    'docs.regen.network': RegenNetworkSite,  # Use same handler
    'guides.regen.network': RegenNetworkSite,  # Use same handler
    'registry.regen.network': RegenNetworkSite,  # Use same handler
    'regencommons.discourse.group': ForumRegenSite,  # Discourse forum
}

__all__ = ['BaseSite', 'SITE_HANDLERS']