from typing import Callable, Dict, Any

# Simple in-memory state store
# Replace later with Redis or DB table
_user_states: Dict[str, str] = {}

def get_state(user_id: str) -> str:
    return _user_states.get(user_id, "idle")

def set_state(user_id: str, state: str):
    _user_states[user_id] = state

def clear_state(user_id: str):
    _user_states.pop(user_id, None)


class StateMachine:
    def __init__(self, name: str, states: list[str], transitions: dict, handlers: dict[str, Callable]):
        """
        :param name: workflow name
        :param states: list of valid states
        :param transitions: {state: [allowed_next_states]}
        :param handlers: {state: function(msg) -> str}
        """
        self.name = name
        self.states = states
        self.transitions = transitions
        self.handlers = handlers

    def handle(self, user_id: str, msg: Any) -> str:
        state = get_state(user_id)
        if state not in self.states:
            state = "idle"
            set_state(user_id, state)

        handler = self.handlers.get(state)
        if not handler:
            return "Sorry, I cannot handle this step."

        reply, next_state = handler(msg)

        if next_state and next_state in self.transitions.get(state, []):
            set_state(user_id, next_state)
        elif next_state == "end":
            clear_state(user_id)

        return reply
