from dataclasses import dataclass
from typing import Optional
import numpy as np

@dataclass
class ParentChunk:
    id: str
    notebook_id: str
    document_id: str
    text: str
    order: int
    score: Optional[float] = 1.0

@dataclass
class ChildChunk:
    id: str
    parent_id: str
    source_id: str
    text: str
    order: int
    embedding: Optional[np.ndarray] = None
