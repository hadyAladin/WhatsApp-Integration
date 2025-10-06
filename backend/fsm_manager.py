# backend/fsm_manager.py
import logging

from backend.fsm import step

logger = logging.getLogger("fsm_manager")
logger.setLevel(logging.INFO)

def get_state(participant_id: str, workflow_name: str) -> str:
    """
    Fetch the current state for a participant/workflow from Supabase.
    Defaults to 'START' if not found.
    """
    resp = (
        supabase.table("conversation_state")
        .select("state")
        .eq("participant_id", participant_id)
        .eq("workflow_name", workflow_name)
        .execute()
    )

    if resp.data and len(resp.data) > 0:
        state = resp.data[0]["state"]
        logger.info(f"Loaded state={state} for participant={participant_id}, workflow={workflow_name}")
        return state

    logger.info(f"No state found, defaulting to START for participant={participant_id}")
    return "START"


def save_state(participant_id: str, workflow_name: str, new_state: str):
    """
    Save or update the current state for a participant/workflow in Supabase.
    """
    payload = {
        "participant_id": participant_id,
        "workflow_name": workflow_name,
        "state": new_state,
    }

    resp = (
        supabase.table("conversation_state")
        .upsert(payload, on_conflict="participant_id,workflow_name")  # ✅ fixed
        .execute()
    )
    logger.info(f"Saved state={new_state} for participant={participant_id}, workflow={workflow_name}")
    return resp


def advance_state(participant_id: str, workflow_name: str, intent: str) -> str:
    """
    Move the participant to the next state based on intent.
    """
    current_state = get_state(participant_id, workflow_name)
    logger.info(f"advance_state called: {participant_id} {workflow_name} {intent}")

    new_state = step(current_state, intent, workflow_name)  # ✅ ensure workflow passed
    save_state(participant_id, workflow_name, new_state)

    return new_state

if __name__ == "__main__":
    from backend.connect_supabase import supabase
    print(supabase.table("conversation_state").select("*").limit(1).execute())
