from app.services.authentication.auth_service import supabase

def get_user_notebooks(user_id: str):
    """Fetch all notebooks belonging to a specific user from Supabase."""
    try:
        response = supabase.table("notebooks").select("*").eq("user_id", user_id).execute()
        return response.data or []
    except Exception:
        # Table might not exist yet in a new Supabase project
        return []

def get_notebook_by_id(notebook_id: str, user_id: str):
    """Fetch a specific notebook, ensuring it belongs to the requesting user."""
    try:
        response = supabase.table("notebooks").select("*").eq("id", notebook_id).eq("user_id", user_id).execute()
        if not response.data:
            return None
        return response.data[0]
    except Exception:
        return None