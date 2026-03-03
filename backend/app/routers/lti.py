from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.post("/login", summary="LTI OIDC login initiation")
async def lti_login(request: Request):
    """
    Step 1 of the LTI 1.3 OIDC launch flow.
    Receives login initiation from the LMS and redirects to the LMS
    OIDC auth endpoint with a state and nonce stored in Redis.
    """
    # TODO: implement via PyLTI1p3
    pass


@router.post("/launch", summary="LTI OIDC launch callback")
async def lti_launch(request: Request):
    """
    Step 3 of the LTI 1.3 OIDC launch flow.
    Validates the signed JWT from the LMS, consumes the nonce,
    resolves the context to a reading list, and redirects appropriately.

    - Instructor/admin roles → editor view
    - Student/unknown roles → public list view (no identity stored)
    """
    # TODO: implement via PyLTI1p3
    pass


@router.post("/deep-link", summary="LTI Deep Linking response handler")
async def lti_deep_link(request: Request):
    """
    Handles Deep Linking content item selection.
    Returns a signed DeepLinkingResponse JWT to the LMS.
    """
    # TODO: implement via PyLTI1p3
    pass


@router.get("/jwks", summary="Tool public JWKS endpoint")
async def lti_jwks():
    """
    Returns the tool's public key in JWKS format.
    Registered with the LMS during tool configuration.
    """
    # TODO: return tool public keys
    return {"keys": []}
