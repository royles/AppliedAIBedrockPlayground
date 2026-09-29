"""Bedrock catalog: regions, models, and inference routing."""

from app.schemas import ModelInfo
from app.state import runtime_state

# Geo scopes shown in the region dropdown (not valid boto3 region names).
GEO_SCOPES = frozenset({"global", "eu", "us", "au"})

# boto3 client region used for each geo scope.
GEO_CLIENT_REGIONS: dict[str, str] = {
    "global": "us-east-1",
    "us": "us-east-1",
    "eu": "eu-west-1",
    "au": "ap-southeast-2",
}

# Region options exposed in the UI (geo inference scopes).
BEDROCK_REGIONS: list[str] = [
    "global",
    "eu",
    "us",
    "us-east-1",
]

# Curated Bedrock models for the playground.
AVAILABLE_MODELS: list[ModelInfo] = [
    ModelInfo(
        model_id="anthropic.claude-sonnet-5",
        provider="Anthropic",
        display_name="Claude Sonnet 5",
    ),
    ModelInfo(
        model_id="anthropic.claude-sonnet-4-6",
        provider="Anthropic",
        display_name="Claude Sonnet 4.6",
    ),
    ModelInfo(
        model_id="anthropic.claude-opus-4-8",
        provider="Anthropic",
        display_name="Claude Opus 4.8",
    ),
]

class CatalogError(Exception):
    """Raised when the Bedrock catalog is missing required configuration."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def resolve_bedrock_client_region(ui_region: str) -> str:
    """Return a real AWS region for boto3 bedrock-runtime clients."""
    return GEO_CLIENT_REGIONS.get(ui_region, ui_region)


def resolve_inference_model_id(base_model_id: str, ui_region: str) -> str:
    """
    Return the model / inference-profile ID to pass to InvokeModel.

    Geo scopes require prefixed inference profile IDs such as
    `global.anthropic.claude-sonnet-5`.
    """
    if any(base_model_id.startswith(f"{scope}.") for scope in GEO_SCOPES):
        return base_model_id
    if ui_region in GEO_SCOPES:
        return f"{ui_region}.{base_model_id}"
    return base_model_id


def get_bedrock_regions() -> list[str]:
    if not BEDROCK_REGIONS:
        raise CatalogError(
            "Bedrock region list is empty. Add entries to BEDROCK_REGIONS in models_catalog.py."
        )
    return list(BEDROCK_REGIONS)


def get_bedrock_models() -> list[ModelInfo]:
    if not AVAILABLE_MODELS:
        raise CatalogError(
            "Bedrock model list is empty. Add entries to AVAILABLE_MODELS in models_catalog.py."
        )
    return list(AVAILABLE_MODELS)


def allowed_model_ids() -> set[str]:
    return {model.model_id for model in AVAILABLE_MODELS}


def is_valid_region(region: str) -> bool:
    return region in BEDROCK_REGIONS


def get_model_info(model_id: str) -> ModelInfo | None:
    for model in AVAILABLE_MODELS:
        if model.model_id == model_id:
            return model
    return None


def normalize_bedrock_selection() -> None:
    """Align runtime region/model with catalog entries when possible."""
    if BEDROCK_REGIONS and runtime_state.get_region() not in BEDROCK_REGIONS:
        runtime_state.set_region(BEDROCK_REGIONS[0])
    if AVAILABLE_MODELS and runtime_state.get_model_id() not in allowed_model_ids():
        runtime_state.set_model_id(AVAILABLE_MODELS[0].model_id)


def bedrock_catalog_status() -> tuple[bool, str | None]:
    """
    Return (ready, error_message).
    Bedrock chat requires AWS credentials plus a non-empty, valid catalog selection.
    """
    if not BEDROCK_REGIONS:
        return False, "No Bedrock regions configured."
    if not AVAILABLE_MODELS:
        return False, "No Bedrock models configured."

    region = runtime_state.get_region()
    model_id = runtime_state.get_model_id()
    if region not in BEDROCK_REGIONS:
        return False, f"Selected region '{region}' is not available."
    if model_id not in allowed_model_ids():
        return False, f"Selected model '{model_id}' is not available."
    return True, None
