from __future__ import annotations
import reflex as rx
from .agents import answer

class ControlRoomState(rx.State):
    prompt: str = ""
    response: str = "Ask Hermes Control what is happening. Answers are grounded in kernel evidence."
    evidence: list[str] = []
    specialists: list[str] = []
    run_id: str = ""

    @rx.event
    def set_prompt(self, value: str):
        self.prompt = value

    @rx.event
    async def ask(self):
        if not self.prompt.strip():
            return
        result = await answer(self.prompt.strip())
        self.response = result.answer
        self.evidence = [f"{e.source} · {e.claim}: {e.value}" for e in result.evidence]
        self.specialists = result.specialists
        self.run_id = result.run_id or ""

def index():
    return rx.box(
        rx.hstack(
            rx.vstack(rx.text("TENET", size="6", weight="bold"), rx.text("CONTROL ROOM v2", color="#7d8b9c", size="2"), align_items="start", spacing="0"),
            rx.spacer(), rx.badge("TENET kernel authority", color_scheme="green"), width="100%",
        ),
        rx.grid(
            rx.box(rx.text("CURRENT ACTION", size="2", weight="bold"), rx.text("Action → Why → Who → Authority → Policy → Decision → Execution → Proof"), background="#10151c", padding="18px", border="1px solid #1e2733", border_radius="12px"),
            rx.box(rx.text("AGENT TOPOLOGY", size="2", weight="bold"), rx.text("Hermes Control Orchestrator → Governance · Kernel · Control-Plane"), background="#10151c", padding="18px", border="1px solid #1e2733", border_radius="12px"),
            columns="2", spacing="4", width="100%",
        ),
        rx.box(
            rx.text("Hermes Control", size="4", weight="bold"),
            rx.text("Ask about the system. The answer is grounded in observed kernel evidence.", color="#9db0c6"),
            rx.input(value=ControlRoomState.prompt, on_change=ControlRoomState.set_prompt, placeholder="Why was support-copilot blocked?"),
            rx.button("Ask", on_click=ControlRoomState.ask, color_scheme="orange"),
            rx.text(ControlRoomState.response, color="white"),
            rx.foreach(ControlRoomState.evidence, lambda item: rx.text(item, size="2", color="#9db0c6")),
            rx.cond(ControlRoomState.run_id != "", rx.text("run_id: " + ControlRoomState.run_id, size="1", color="#56616f"), rx.fragment()),
            background="#0d131b", border="1px solid #22303f", border_radius="12px", padding="20px", spacing="3",
        ),
        background="#0a0e13", min_height="100vh", color="white", padding="28px", spacing="5",
    )

app = rx.App(theme=rx.theme(appearance="dark"))
app.add_page(index, title="TENET Control Room")
