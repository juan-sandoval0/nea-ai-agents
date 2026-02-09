"""
Tests for Prompt Registry and Model Configuration
=================================================

Tests versioning, hashing, and change detection for prompts and models.
"""

import pytest
from core.prompt_registry import (
    Prompt,
    ModelConfig,
    ModelProvider,
    PromptRegistry,
    LLMCallMetadata,
    get_prompt,
    get_model_config,
    get_registry,
)


# =============================================================================
# TEST: Prompt
# =============================================================================

class TestPrompt:
    """Tests for Prompt dataclass."""

    def test_prompt_creation(self):
        """Prompt is created with all required fields."""
        prompt = Prompt(
            id="test_prompt",
            name="Test Prompt",
            version="1.0.0",
            content="You are a helpful assistant.",
        )
        assert prompt.id == "test_prompt"
        assert prompt.name == "Test Prompt"
        assert prompt.version == "1.0.0"
        assert prompt.content == "You are a helpful assistant."

    def test_content_hash_computed(self):
        """Content hash is computed on creation."""
        prompt = Prompt(
            id="test",
            name="Test",
            version="1.0.0",
            content="Test content",
        )
        assert len(prompt.content_hash) == 12  # First 12 chars of SHA-256
        assert prompt.content_hash.isalnum()

    def test_content_hash_changes_with_content(self):
        """Different content produces different hashes."""
        prompt1 = Prompt(id="p1", name="P1", version="1.0.0", content="Content A")
        prompt2 = Prompt(id="p2", name="P2", version="1.0.0", content="Content B")
        assert prompt1.content_hash != prompt2.content_hash

    def test_same_content_same_hash(self):
        """Same content produces same hash regardless of other fields."""
        prompt1 = Prompt(id="p1", name="P1", version="1.0.0", content="Same content")
        prompt2 = Prompt(id="p2", name="P2", version="2.0.0", content="Same content")
        assert prompt1.content_hash == prompt2.content_hash

    def test_full_id_format(self):
        """Full ID includes version and hash."""
        prompt = Prompt(id="test", name="Test", version="1.0.0", content="Content")
        # Format: id@version#hash
        assert prompt.full_id.startswith("test@1.0.0#")
        assert len(prompt.full_id.split("#")[1]) == 12

    def test_to_dict(self):
        """to_dict returns serializable dict."""
        prompt = Prompt(
            id="test",
            name="Test",
            version="1.0.0",
            content="Content",
            description="A test prompt",
        )
        d = prompt.to_dict()
        assert d["id"] == "test"
        assert d["version"] == "1.0.0"
        assert "content_hash" in d
        assert "full_id" in d

    def test_format_with_variables(self):
        """Prompt formatting with variables works."""
        prompt = Prompt(
            id="template",
            name="Template",
            version="1.0.0",
            content="Hello {name}, welcome to {place}!",
            variables=["name", "place"],
        )
        result = prompt.format(name="Alice", place="Wonderland")
        assert result == "Hello Alice, welcome to Wonderland!"

    def test_format_missing_variable_raises(self):
        """Missing required variable raises KeyError."""
        prompt = Prompt(
            id="template",
            name="Template",
            version="1.0.0",
            content="Hello {name}!",
            variables=["name"],
        )
        with pytest.raises(KeyError) as exc_info:
            prompt.format()
        assert "name" in str(exc_info.value)


# =============================================================================
# TEST: ModelConfig
# =============================================================================

class TestModelConfig:
    """Tests for ModelConfig dataclass."""

    def test_model_config_creation(self):
        """ModelConfig is created with defaults."""
        config = ModelConfig(name="test", model="gpt-4o-mini")
        assert config.name == "test"
        assert config.model == "gpt-4o-mini"
        assert config.temperature == 0.0
        assert config.provider == ModelProvider.OPENAI

    def test_to_dict(self):
        """to_dict returns serializable dict."""
        config = ModelConfig(
            name="test",
            model="gpt-4o-mini",
            temperature=0.7,
            max_tokens=1000,
        )
        d = config.to_dict()
        assert d["name"] == "test"
        assert d["model"] == "gpt-4o-mini"
        assert d["temperature"] == 0.7
        assert d["max_tokens"] == 1000
        assert d["provider"] == "openai"

    def test_config_hash(self):
        """Config hash changes with parameters."""
        config1 = ModelConfig(name="c1", model="gpt-4o-mini", temperature=0.0)
        config2 = ModelConfig(name="c2", model="gpt-4o-mini", temperature=0.5)
        assert config1.config_hash != config2.config_hash


# =============================================================================
# TEST: PromptRegistry
# =============================================================================

class TestPromptRegistry:
    """Tests for PromptRegistry."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry for each test."""
        return PromptRegistry()

    def test_default_prompts_registered(self, registry):
        """Default prompts are registered on init."""
        prompt = registry.get_prompt("briefing_system")
        assert prompt is not None
        assert "venture capital" in prompt.content.lower()

    def test_default_model_configs_registered(self, registry):
        """Default model configs are registered on init."""
        config = registry.get_model_config("briefing")
        assert config is not None
        assert config.model == "gpt-4o-mini"

    def test_register_new_prompt(self, registry):
        """Can register new prompts."""
        prompt = Prompt(
            id="custom",
            name="Custom",
            version="1.0.0",
            content="Custom prompt content",
        )
        registry.register_prompt(prompt)

        retrieved = registry.get_prompt("custom")
        assert retrieved.content == "Custom prompt content"

    def test_get_nonexistent_prompt_raises(self, registry):
        """Getting nonexistent prompt raises KeyError."""
        with pytest.raises(KeyError):
            registry.get_prompt("nonexistent")

    def test_list_prompts(self, registry):
        """list_prompts returns all registered prompts."""
        prompts = registry.list_prompts()
        assert isinstance(prompts, list)
        assert len(prompts) >= 2  # At least the default prompts
        assert all("id" in p for p in prompts)

    def test_list_model_configs(self, registry):
        """list_model_configs returns all registered configs."""
        configs = registry.list_model_configs()
        assert isinstance(configs, list)
        assert len(configs) >= 2  # At least the default configs
        assert all("model" in c for c in configs)

    def test_get_prompt_changes_detects_change(self, registry):
        """get_prompt_changes detects content changes."""
        # Get registered content
        original = registry.get_prompt("briefing_system").content

        # Modify content
        modified = original + "\n\nNew instruction added."

        changes = registry.get_prompt_changes("briefing_system", modified)
        assert changes is not None
        assert changes["status"] == "changed"
        assert "current_hash" in changes

    def test_get_prompt_changes_no_change(self, registry):
        """get_prompt_changes returns None for unchanged content."""
        original = registry.get_prompt("briefing_system").content

        changes = registry.get_prompt_changes("briefing_system", original)
        assert changes is None

    def test_get_prompt_changes_new_prompt(self, registry):
        """get_prompt_changes returns 'new' for unregistered prompts."""
        changes = registry.get_prompt_changes("new_prompt", "Some content")
        assert changes is not None
        assert changes["status"] == "new"


# =============================================================================
# TEST: LLMCallMetadata
# =============================================================================

class TestLLMCallMetadata:
    """Tests for LLMCallMetadata."""

    def test_create_basic(self):
        """Basic metadata creation works."""
        metadata = LLMCallMetadata.create(operation="test")
        assert metadata.operation == "test"
        assert metadata.call_id  # UUID generated
        assert metadata.timestamp

    def test_create_with_prompt(self):
        """Metadata includes prompt info when provided."""
        prompt = Prompt(
            id="test_prompt",
            name="Test",
            version="1.0.0",
            content="Test content",
        )
        metadata = LLMCallMetadata.create(
            operation="test",
            prompt=prompt,
        )
        assert metadata.prompt_id == "test_prompt"
        assert metadata.prompt_version == "1.0.0"
        assert metadata.prompt_hash == prompt.content_hash

    def test_create_with_model_config(self):
        """Metadata includes model config when provided."""
        config = ModelConfig(
            name="test_config",
            model="gpt-4o",
            temperature=0.5,
            max_tokens=2000,
        )
        metadata = LLMCallMetadata.create(
            operation="test",
            model_config=config,
        )
        assert metadata.model == "gpt-4o"
        assert metadata.model_config_name == "test_config"
        assert metadata.temperature == 0.5
        assert metadata.max_tokens == 2000

    def test_create_with_prompt_hashes(self):
        """System and user prompt hashes are computed."""
        metadata = LLMCallMetadata.create(
            operation="test",
            system_prompt="You are helpful.",
            user_prompt="What is 2+2?",
        )
        assert metadata.system_prompt_hash
        assert len(metadata.system_prompt_hash) == 12
        assert metadata.user_prompt_hash
        assert len(metadata.user_prompt_hash) == 12

    def test_to_dict(self):
        """to_dict returns complete dict."""
        metadata = LLMCallMetadata.create(
            operation="briefing",
            company_id="test.com",
        )
        d = metadata.to_dict()
        assert d["operation"] == "briefing"
        assert d["company_id"] == "test.com"
        assert "call_id" in d
        assert "timestamp" in d


# =============================================================================
# TEST: Global Functions
# =============================================================================

class TestGlobalFunctions:
    """Tests for module-level convenience functions."""

    def test_get_registry_returns_singleton(self):
        """get_registry returns the same instance."""
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2

    def test_get_prompt_convenience(self):
        """get_prompt function works."""
        prompt = get_prompt("briefing_system")
        assert prompt is not None
        assert prompt.id == "briefing_system"

    def test_get_model_config_convenience(self):
        """get_model_config function works."""
        config = get_model_config("briefing")
        assert config is not None
        assert config.name == "briefing"
