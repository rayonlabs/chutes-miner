import base64
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from chutes_common.auth import authorize
from chutes_miner_gpu.api.settings import Settings
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger


router = APIRouter()

settings = Settings()


async def get_kubeconfig_from_secret(
    secret_name: str = "miner-kubeconfig", namespace: str = "default"
) -> str:
    """
    Retrieve kubeconfig from a Kubernetes secret.

    Args:
        secret_name (str): Name of the secret containing kubeconfig
        namespace (str): Namespace where the secret is located

    Returns:
        str: Decoded kubeconfig content

    Raises:
        HTTPException: Various HTTP exceptions based on the error type
    """
    try:
        # Load the current cluster config (assumes running in-cluster or with valid kubeconfig)
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                logger.warning("Falling back to kubeconfig")
                config.load_kube_config()
            except config.ConfigException:
                raise HTTPException(
                    status_code=500, detail="Unable to load Kubernetes configuration"
                )

        # Create API client
        v1 = client.CoreV1Api()

        # Get the secret
        secret = v1.read_namespaced_secret(name=secret_name, namespace=namespace)

        # Extract and decode the kubeconfig
        if "kubeconfig" not in secret.data:
            raise HTTPException(
                status_code=500, detail=f"Secret {secret_name} does not contain 'kubeconfig' key"
            )

        kubeconfig_b64 = secret.data["kubeconfig"]
        kubeconfig_content = base64.b64decode(kubeconfig_b64).decode("utf-8")
        return kubeconfig_content

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404, detail=f"Secret {secret_name} not found in namespace {namespace}"
            )
        elif e.status == 403:
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied accessing secret {secret_name} in namespace {namespace}",
            )
        else:
            raise HTTPException(status_code=500, detail=f"Error retrieving secret: {e.reason}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading kubeconfig: {str(e)}")


@router.get("/kubeconfig")
async def get_miner_kubeconfig(
    _: None = Depends(authorize(allow_miner=True, purpose="registration")),
):
    """
    Get the kubeconfig for the miner role from Kubernetes secret
    """
    try:
        # Get kubeconfig from the miner-credentials secret in default namespace
        kubeconfig_content = await get_kubeconfig_from_secret(
            secret_name="miner-kubeconfig", namespace="default"
        )

        return {"kubeconfig": kubeconfig_content}

    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except Exception as e:
        # Catch any unexpected errors
        raise HTTPException(
            status_code=500, detail=f"Unexpected error retrieving kubeconfig: {str(e)}"
        )
