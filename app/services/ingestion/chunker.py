import uuid
import re
import tiktoken
from chonkie import RecursiveChunker, RecursiveRules, RecursiveLevel
from app.models.ingestion_models import ParentChunk, ChildChunk
from app.services.ingestion.config import PARENT_CHUNK_TOKENS, PARENT_OVERLAP_TOKENS, CHILD_CHUNK_TOKENS, CHILD_OVERLAP_TOKENS

WORD_SPLIT_RE = re.compile(r'([a-zA-Z])[-\u2010\xad][ \t]*\n[ \t]*([a-z])')
ACRONYM_MATH_SPLIT_RE = re.compile(r'([A-Z0-9])[-\u2010\xad][ \t]*\n[ \t]*([A-Z0-9])')
EXCESSIVE_NEWLINES_RE = re.compile(r'\n(?:[ \t]*\n){2,}')

custom_rules = RecursiveRules([
    RecursiveLevel(delimiters=["\n\n", "\r\n\r\n"], include_delim="prev"),
    RecursiveLevel(delimiters=["\n", "\r\n"], include_delim="prev"),
    RecursiveLevel(delimiters=[". ", "? ", "! ", ".\n", '." ', '!" '], include_delim="prev"),
    RecursiveLevel(delimiters=[", ", "; ", ": ", " - ", " — "], include_delim="prev"),
    RecursiveLevel(whitespace=True, include_delim="prev")
])

class HierarchicalChunker:
    """Wraps chonkie and applies word-safe overlap manually."""
    def __init__(self) -> None:
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        
        self._parent_splitter = RecursiveChunker(
            tokenizer=self.tokenizer, 
            chunk_size=PARENT_CHUNK_TOKENS, 
            rules=custom_rules
        )
        self._child_splitter = RecursiveChunker(
            tokenizer=self.tokenizer,
            chunk_size=CHILD_CHUNK_TOKENS,
            rules=custom_rules
        )

    def _get_safe_overlap(self, text: str, max_tokens: int) -> str:
        if not text or max_tokens <= 0:
            return ""
        tokens = self.tokenizer.encode(text)
        if len(tokens) <= max_tokens:
            return text.lstrip()
        # Decode only the trailing token slice to avoid O(N^2) token encoding loops
        candidate = self.tokenizer.decode(tokens[-max_tokens:])
        parts = re.findall(r'\S+|\s+', candidate)
        overlap_str = ""
        for part in reversed(parts):
            test_str = part + overlap_str
            if len(self.tokenizer.encode(test_str)) > max_tokens:
                break
            overlap_str = test_str
        return overlap_str.lstrip()

    def clean_pdf_text(self, text: str) -> str:
        if not text:
            return ""
        text = WORD_SPLIT_RE.sub(r'\1\2', text)
        text = ACRONYM_MATH_SPLIT_RE.sub(r'\1-\2', text)
        text = EXCESSIVE_NEWLINES_RE.sub('\n\n', text)
        return text.strip()
    
    def chunk_document(self, text: str, notebook_id: str, document_id: str) -> tuple[list[ParentChunk], list[ChildChunk]]:
        parents: list[ParentChunk] = []
        children: list[ChildChunk] = []
        cleaned_text = self.clean_pdf_text(text)
        base_parent_pieces = self._parent_splitter.chunk(cleaned_text)
        
        for p_idx, p_piece in enumerate(base_parent_pieces):
            if p_idx == 0:
                parent_text = p_piece.text
            else:
                overlap_text = self._get_safe_overlap(base_parent_pieces[p_idx-1].text, PARENT_OVERLAP_TOKENS)
                separator = "" if overlap_text.endswith(("\n", " ", "\t")) or p_piece.text.startswith(("\n", " ", "\t")) else " "
                parent_text = overlap_text + separator + p_piece.text
            
            parent = ParentChunk(
                id=str(uuid.uuid4()),
                notebook_id=notebook_id,
                document_id=document_id,
                text=parent_text,
                order=p_idx,
            )
            parents.append(parent)

            base_child_pieces = self._child_splitter.chunk(parent_text)
            for c_idx, c_piece in enumerate(base_child_pieces):
                if c_idx == 0:
                    child_text = c_piece.text
                else:
                    child_overlap = self._get_safe_overlap(base_child_pieces[c_idx-1].text, CHILD_OVERLAP_TOKENS)
                    separator = "" if child_overlap.endswith(("\n", " ", "\t")) or c_piece.text.startswith(("\n", " ", "\t")) else " "
                    child_text = child_overlap + separator + c_piece.text
                    
                children.append(
                    ChildChunk(
                        id=str(uuid.uuid4()), 
                        parent_id=parent.id, 
                        source_id=document_id,
                        text=child_text, 
                        order=c_idx
                    )
                )
        return parents, children