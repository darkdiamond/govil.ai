"""
Configuration settings for the Scanner Service.

Firestore-backed — no local database or download directory.
"""


from pydantic_settings import BaseSettings, SettingsConfigDict


class ScannerSettings(BaseSettings):
    """Scanner service configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # CKAN API
    ckan_base_url: str = "https://data.gov.il/api/3/action"
    ckan_request_delay: float = 0.5
    ckan_timeout: int = 30
    ckan_max_retries: int = 3

    # Firestore
    firestore_project_id: str | None = None  # falls back to GOOGLE_CLOUD_PROJECT
    firestore_database: str = "(default)"

    # Scanner defaults
    default_limit: int = 5
    default_timeout: int = 30

    # Logging
    log_level: str = "INFO"

    # Excluded file formats (the builder/agent handles its own filtering;
    # scanner keeps this only so CLI summaries match what the agent will see).
    EXCLUDED_FORMATS: list[str] = [
        "PDF", "DOC", "DOCX", "ZIP", "RAR", "7Z", "EXE", "MSI",
    ]

    # Excluded dataset IDs — updates too frequently to be worth building pages for.
    EXCLUDED_DATASET_IDS: list[str] = [
        "3dfc6b2a-bc1d-4770-8d5f-457ce50a73b3",  # מאגר טיסות
    ]

    @property
    def package_list_url(self) -> str:
        return f"{self.ckan_base_url}/package_list"

    @property
    def package_search_url(self) -> str:
        return f"{self.ckan_base_url}/package_search"

    @property
    def package_show_url(self) -> str:
        return f"{self.ckan_base_url}/package_show"

    @property
    def datastore_search_url(self) -> str:
        return f"{self.ckan_base_url}/datastore_search"

    def get_datastore_dump_url(self, resource_id: str) -> str:
        return f"{self.ckan_base_url}/datastore_search?resource_id={resource_id}&limit=1000000"


settings = ScannerSettings()
