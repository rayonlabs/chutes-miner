from pathlib import Path
from chutes_common.auth import authorize
from chutes_miner_gpu.api.settings import Settings
from fastapi import APIRouter, Depends, HTTPException


router = APIRouter()

settings = Settings()


@router.get("/kubeconfig")
async def get_miner_kubeconfig(
    _: None = Depends(authorize(allow_validator=True, purpose="management")),
):
    """
    Get the kubeconfig for the miner role
    """
    try:
        kubeconfig_path = Path(settings.miner_kube_config)

        if not kubeconfig_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Kubeconfig file not found at {kubeconfig_path}"
            )

        if not kubeconfig_path.is_file():
            raise HTTPException(status_code=400, detail=f"Path {kubeconfig_path} is not a file")

        # Read the kubeconfig file contents
        with open(kubeconfig_path, "r", encoding="utf-8") as file:
            kubeconfig_content = file.read()

        return {"kubeconfig": kubeconfig_content}

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Kubeconfig file not found at {settings.miner_kube_config}"
        )
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied reading kubeconfig file at {settings.miner_kube_config}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading kubeconfig file: {str(e)}")
