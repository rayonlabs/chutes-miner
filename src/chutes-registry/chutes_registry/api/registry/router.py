"""
Authentication helper for pulling images with miner credentials.
"""

from chutes_common.auth import sign_request
from ipaddress import ip_address
from fastapi import Request, Response, APIRouter, HTTPException, status

router = APIRouter()


@router.get("/auth")
async def registry_auth(
    request: Request,
    response: Response,
):
    ip = ip_address(request.client.host)
    is_private = (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
    if not is_private:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="go away",
        )
    headers, _ = sign_request(payload=None, purpose="registry")
    response.headers.update(headers)
    return {"authenticated": True}
