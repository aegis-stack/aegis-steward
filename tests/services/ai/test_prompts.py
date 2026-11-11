"""Tests for system prompt assembly (persona override)."""

from app.services.ai.domains.chat.prompts import build_system_prompt


class TestPersonaOverride:
    def test_default_prompt_uses_builtin_persona(self) -> None:
        prompt = build_system_prompt()

        assert prompt.startswith("I'm Illiana.")

    def test_the_builtin_persona_reads_the_app_through_its_tools(self) -> None:
        """Not a stack list from memory, nor a claim it cannot see the code:
        she reads the app with her tools and draws what she finds."""
        prompt = build_system_prompt()

        assert "ontology tool" in prompt
        assert "I draw it as a card" in prompt
        assert "Flet" not in prompt
        assert "don't have codebase access" not in prompt

    def test_persona_replaces_builtin_block(self) -> None:
        prompt = build_system_prompt(persona="You are Custom.")

        assert prompt.startswith("You are Custom.")
        assert "I'm Illiana" not in prompt

    def test_persona_keeps_dynamic_context_sections(self) -> None:
        """A custom persona still gets the live-data sections appended."""
        prompt = build_system_prompt(
            persona="You are Custom.",
            health_context="ALL COMPONENTS HEALTHY",
            usage_context="42 requests today",
        )

        assert prompt.startswith("You are Custom.")
        assert "## System Status" in prompt
        assert "ALL COMPONENTS HEALTHY" in prompt
        assert "## My Activity" in prompt


class TestMemoryContext:
    def test_memory_context_section_is_appended(self) -> None:
        prompt = build_system_prompt(
            memory_context="<user_memory>\n- [food] vegan\n</user_memory>",
        )

        assert "## Saved User Memory" in prompt
        assert "<user_memory>" in prompt
        assert "- [food] vegan" in prompt

    def test_no_memory_context_no_section(self) -> None:
        prompt = build_system_prompt()

        assert "## Saved User Memory" not in prompt

    def test_catalog_context_renders_as_body_under_heading(self) -> None:
        """The catalog payload is body text, never part of the heading line."""
        catalog = "- gpt-x: fast\n- gpt-y: smart"
        prompt = build_system_prompt(catalog_context=catalog)

        assert catalog in prompt
        first_line = next(line for line in prompt.splitlines() if "gpt-x" in line)
        assert not first_line.startswith("#")
