"""Email Sensor for Personal-KOI — lazy module loading.

Eager imports broke package-style loading because internal modules use flat
imports (e.g. `from maildir_parser import ...`) that rely on sys.path containing
`sensors/email/`. The lazy __getattr__ pattern keeps `from sensors.email import X`
working for consumers that add the directory to sys.path, while not exploding
when `sensors.email.Y` is imported from outside (e.g. `from sensors.email.ics_writer
import process_ics_attachments`).
"""

_LAZY = {
    'EmailSensor': ('email_sensor', 'EmailSensor'),
    'MaildirParser': ('maildir_parser', 'MaildirParser'),
    'EmailChunker': ('chunker', 'EmailChunker'),
    'SentenceAwareChunker': ('chunker', 'SentenceAwareChunker'),
    'EmailEmbedder': ('embedder', 'EmailEmbedder'),
    'EmailEntityExtractor': ('email_entity_extractor', 'EmailEntityExtractor'),
    'AttachmentProcessor': ('attachment_processor', 'AttachmentProcessor'),
}


def __getattr__(name):
    if name in _LAZY:
        import importlib
        mod_name, attr = _LAZY[name]
        try:
            mod = importlib.import_module(f'sensors.email.{mod_name}')
        except ImportError:
            mod = importlib.import_module(mod_name)
        return getattr(mod, attr)
    raise AttributeError(f"module 'sensors.email' has no attribute {name!r}")


__all__ = list(_LAZY.keys())
