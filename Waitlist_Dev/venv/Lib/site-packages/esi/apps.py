from django.apps import AppConfig


class EsiConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'esi'
    verbose_name = 'EVE Swagger Interface (SSO v2)'

    def ready(self) -> None:
        super().ready()
        from esi import checks  # noqa
