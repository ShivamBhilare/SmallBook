from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# ==========================================
# GENERATION REQUEST PAYLOADS
# ==========================================

class StudyGenerateRequest(BaseModel):
    source_id: str = Field(..., description="UUID of the selected source document")
    tool_type: Literal["flashcards", "quiz"] = Field(..., description="Type of study tool to generate")
    custom_prompt: Optional[str] = Field(None, max_length=1000, description="Optional focus instructions or guidance")
    num_items: Optional[int] = Field(None, description="Optional item count override")
    model: Optional[str] = Field(None, description="Optional requested LLM model override")


# ==========================================
# LLM STRUCTURED OUTPUT SCHEMAS
# ==========================================

class FlashcardItemSchema(BaseModel):
    front_text: str = Field(..., description="Question, prompt, key concept, or term")
    back_text: str = Field(..., description="Clear, concise, and accurate answer or definition grounded in the text")
    source_chunk_id: Optional[str] = Field(None, description="UUID of the chunk supporting this flashcard, if provided in context")


class FlashcardSetGenerateSchema(BaseModel):
    title: str = Field(..., description="Concise descriptive title for this flashcard deck")
    cards: List[FlashcardItemSchema] = Field(..., description="List of generated flashcards")


class QuizOptionSchema(BaseModel):
    key: str = Field(..., description="Option letter: 'A', 'B', 'C', or 'D'")
    text: str = Field(..., description="Option description text")


class QuizQuestionSchema(BaseModel):
    question_text: str = Field(..., description="The multiple choice question")
    options: List[QuizOptionSchema] = Field(..., min_length=2, max_length=6, description="List of selectable options")
    correct_answer: str = Field(..., description="The key of the correct option (e.g. 'A')")
    explanation: Optional[str] = Field(None, description="Explanation grounded in the text explaining why the answer is correct")
    source_chunk_id: Optional[str] = Field(None, description="UUID of the chunk supporting this question, if provided in context")


class QuizGenerateSchema(BaseModel):
    title: str = Field(..., description="Concise descriptive title for this quiz")
    questions: List[QuizQuestionSchema] = Field(..., description="List of generated quiz questions")


# ==========================================
# DATABASE & RESPONSE SCHEMAS
# ==========================================

class FlashcardResponse(BaseModel):
    id: UUID
    set_id: UUID
    order_index: int
    front_text: str
    back_text: str
    source_chunk_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FlashcardSetResponse(BaseModel):
    id: UUID
    notebook_id: UUID
    user_id: UUID
    source_id: Optional[UUID] = None
    title: str
    custom_prompt: Optional[str] = None
    cards_count: Optional[int] = 0
    cards: Optional[List[FlashcardResponse]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuizQuestionResponse(BaseModel):
    id: UUID
    quiz_id: UUID
    order_index: int
    question_text: str
    question_type: str = "multiple_choice"
    options: List[Dict[str, Any]]
    correct_answer: str
    explanation: Optional[str] = None
    source_chunk_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuizResponse(BaseModel):
    id: UUID
    notebook_id: UUID
    user_id: UUID
    source_id: Optional[UUID] = None
    title: str
    custom_prompt: Optional[str] = None
    questions_count: Optional[int] = 0
    questions: Optional[List[QuizQuestionResponse]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# QUIZ ATTEMPT & SUBMISSION SCHEMAS
# ==========================================

class QuizAttemptSubmit(BaseModel):
    user_answers: Dict[str, str] = Field(..., description="Map of question_id or order_index to selected option key ('A', 'B', etc.)")


class QuestionResult(BaseModel):
    question_id: str
    user_answer: Optional[str] = None
    correct_answer: str
    is_correct: bool
    explanation: Optional[str] = None


class QuizAttemptResponse(BaseModel):
    score: int
    total_questions: int
    percentage: float
    results: List[QuestionResult]


# ==========================================
# NOTE SCHEMAS
# ==========================================

class NoteCreateRequest(BaseModel):
    title: Optional[str] = Field("Untitled Note", max_length=255, description="Title of the note")
    content: str = Field(..., description="Markdown or text content of the note")
    source_message_id: Optional[str] = Field(None, description="Optional ID of the chat message this note was saved from")


class NoteUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=255, description="Updated title of the note")
    content: Optional[str] = Field(None, description="Updated markdown or text content of the note")


class NoteResponse(BaseModel):
    id: UUID
    notebook_id: UUID
    user_id: UUID
    title: str
    content: str
    source_message_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

