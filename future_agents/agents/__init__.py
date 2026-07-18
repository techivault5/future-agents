"""Domain-specific agents."""

from future_agents.agents.pdf_agent import PDFAgent
from future_agents.agents.ppt_agent import PPTAgent
from future_agents.agents.quality_assessor_agent import QualityAssessorAgent
from future_agents.agents.word_agent import WordAgent

__all__ = ["PPTAgent", "WordAgent", "PDFAgent", "QualityAssessorAgent"]
