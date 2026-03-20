import google.auth
import google.auth.transport.requests
from openai import OpenAI

VERTEX_ENDPOINT = (
    "https://europe-north1-aiplatform.googleapis.com/v1beta1"
    "/projects/ainm26osl-716/locations/europe-north1/endpoints/openapi"
)


def get_openai_client() -> OpenAI:
    """Return an OpenAI client pointed at Vertex AI's OpenAI-compatible endpoint.

    Uses Application Default Credentials — works automatically on Cloud Run
    (via service account) and locally (via `gcloud auth application-default login`).
    """
    creds, _ = google.auth.default()
    creds.refresh(google.auth.transport.requests.Request())
    return OpenAI(api_key=creds.token, base_url=VERTEX_ENDPOINT)
