from django.apps import AppConfig


class CitationConfig(AppConfig):
    name = 'citation'

    def ready(self):
        """
        this import it's needed to register the handlers in citation.signals
        """
        from . import signals