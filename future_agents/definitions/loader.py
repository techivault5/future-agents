"""Agent Definition Loader — reads YAML/JSON definitions and constructs agents."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from future_agents.definitions.schema import AgentDefinition

logger = logging.getLogger(__name__)

# Try to import yaml, fall back to JSON-only if not available
try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class DefinitionLoader:
    """Loads agent definitions from YAML or JSON files.

    Usage:
        loader = DefinitionLoader()

        # Load a single definition
        defn = loader.load_file("agents/capability.yaml")

        # Load all definitions in a directory
        defns = loader.load_directory("agents/")

        # Load from a dict
        defn = loader.load_dict({...})
    """

    def load_file(self, path: str | Path) -> AgentDefinition:
        """Load an agent definition from a YAML or JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Definition file not found: {path}")

        content = path.read_text()

        if path.suffix in (".yaml", ".yml"):
            if not HAS_YAML:
                raise ImportError(
                    "PyYAML is required to load YAML definitions. "
                    "Install it with: pip install pyyaml"
                )
            data = yaml.safe_load(content)
        elif path.suffix == ".json":
            data = json.loads(content)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")

        defn = AgentDefinition(**data)
        logger.info("Loaded agent definition: %s (type=%s)", defn.name, defn.type)
        return defn

    def load_directory(self, path: str | Path) -> list[AgentDefinition]:
        """Load all agent definitions from a directory."""
        path = Path(path)
        if not path.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        definitions: list[AgentDefinition] = []
        extensions = {".yaml", ".yml", ".json"}

        for file_path in sorted(path.iterdir()):
            if file_path.suffix in extensions and not file_path.name.startswith("_"):
                try:
                    defn = self.load_file(file_path)
                    definitions.append(defn)
                except Exception:
                    logger.exception("Failed to load definition: %s", file_path)

        logger.info("Loaded %d agent definitions from %s", len(definitions), path)
        return definitions

    def load_dict(self, data: dict[str, Any]) -> AgentDefinition:
        """Load an agent definition from a dictionary."""
        return AgentDefinition(**data)

    def validate(self, defn: AgentDefinition) -> list[str]:
        """Validate an agent definition and return a list of warnings."""
        warnings: list[str] = []

        if not defn.skills:
            warnings.append(f"Agent '{defn.name}' has no skills defined")

        if not defn.prompts:
            warnings.append(f"Agent '{defn.name}' has no prompts defined")

        # Check that system prompt exists
        if defn.prompts and not defn.get_prompt("system"):
            warnings.append(f"Agent '{defn.name}' has no 'system' prompt")

        # Check skill intents are unique
        intents = [s.intent for s in defn.skills]
        if len(intents) != len(set(intents)):
            warnings.append(f"Agent '{defn.name}' has duplicate skill intents")

        # Check prompt variables are referenced in templates
        for prompt in defn.prompts:
            for var in prompt.variables:
                if f"{{{var}}}" not in prompt.template:
                    warnings.append(
                        f"Agent '{defn.name}': prompt '{prompt.name}' "
                        f"declares variable '{var}' but doesn't use it"
                    )

        return warnings
