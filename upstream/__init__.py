"""The real upstream behind the gate.

This package is NOT part of the enforcement path (AGENTS.md D6): it is the downstream
service the kernel fronts. It is a separate process reached over MCP streamable HTTP, so
"did this call reach upstream" is answered by *its* access log, never by the kernel's own
counter.
"""
