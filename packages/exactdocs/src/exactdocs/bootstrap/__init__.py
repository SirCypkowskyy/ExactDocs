"""Composition root: the only package allowed to import more than one domain.

It picks adapters, wires domains to each other through ports, and builds the HTTP, MCP and CLI
entry points.
"""
