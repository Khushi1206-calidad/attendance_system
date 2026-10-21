class MigrateDefaultOnlyRouter:
    """Schema changes go through the read-write ``default`` connection only."""

    def allow_migrate(self, db: str, app_label: str, **hints) -> bool:
        return db == "default"
