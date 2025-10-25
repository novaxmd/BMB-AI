from fastapi import Request, HTTPException
from supabase_config import SUPABASE

def verify_supabase_admin(request: Request):
    """
    Verify that the incoming request has a valid Supabase Authorization token
    and that the corresponding user has the 'admin' role in the 'profiles' table.
    Raises HTTPException on failure, returns a dict with user email and role on success.
    """
    token = request.headers.get("Authorization")
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization token")

    token_value = token.replace("Bearer ", "").strip()
    # Validate token and get user info from Supabase Auth
    try:
        user_resp = SUPABASE.auth.get_user(token_value)
    except Exception as e:
        # If Supabase client raises an error when validating token
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Ensure user information exists
    if not user_resp or not getattr(user_resp, "user", None) or not getattr(user_resp.user, "email", None):
        raise HTTPException(status_code=401, detail="Invalid token or user not found")

    user_email = user_resp.user.email

    # Query the profiles table for the user's role
    try:
        result = SUPABASE.table("profiles").select("role").eq("email", user_email).single().execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query profiles: {e}")

    if not result.data or result.data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access forbidden: admin role required")

    return {
        "user": {
            "email": user_email,
            "role": result.data.get("role")
        }
  }
