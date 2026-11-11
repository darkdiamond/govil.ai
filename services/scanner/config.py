"""
Configuration settings for the Scanner Service.

Firestore-backed — no local database or download directory.
"""


from pydantic_settings import BaseSettings, SettingsConfigDict

from services.shared.ckan import ACTION_API


class ScannerSettings(BaseSettings):
    """Scanner service configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # CKAN API
    ckan_base_url: str = ACTION_API
    ckan_request_delay: float = 0.5
    ckan_timeout: int = 30

    # Excluded dataset IDs — updates too frequently to be worth building pages for.
    EXCLUDED_DATASET_IDS: list[str] = [
        "3dfc6b2a-bc1d-4770-8d5f-457ce50a73b3",  # מאגר טיסות
    ]

    @property
    def package_search_url(self) -> str:
        return f"{self.ckan_base_url}/package_search"

    @property
    def package_show_url(self) -> str:
        return f"{self.ckan_base_url}/package_show"

    @property
    def datastore_search_url(self) -> str:
        return f"{self.ckan_base_url}/datastore_search"


settings = ScannerSettings()
