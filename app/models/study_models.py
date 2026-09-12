"""
Study Tools & Studio Domain Data Models

Defines Pydantic schemas for SmallBook's interactive learning features:
    1. Study Generation Requests: Dispatch parameters for Celery background tasks.
    2. LLM Structured Output: Pydantic schemas enforced via LiteLLM/OpenAI/Gemini JSON mode.
    3. Database & Response Schemas: Persisted flashcard decks, quiz questions, and study notes.
    4. Quiz Attempt Evaluation: User option submissions, scoring calculations, and explanations.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# =========================================================================
# 1. GENERATION REQUEST PAYLOADS
# =========================================================================

class StudyGenerateRequest(BaseModel):
    """
    Study Tool Generation Dispatch Payload.

    Carries parameters submitted by the client to trigger background Celery generation
    of flashcards or quizzes from a designated notebook source document.
    """
    source_id: str = Field(..., description="UUID of the selected source document")
    tool_type: Literal["flashcards", "quiz"] = Field(..., description="Type of study tool to generate")
    custom_prompt: Optional[str] = Field(None, max_length=1000, description="Optional focus instructions or guidance")
    num_items: Optional[int] = Field(None, description="Optional item count override")
    model: Optional[str] = Field(None, description="Optional requested LLM model override")


# =========================================================================
# 2. LLM STRUCTURED OUTPUT SCHEMAS (Pydantic JSON Enforcement)
# =========================================================================

class FlashcardItemSchema(BaseModel):
    """
    Individual Flashcard Card Schema.

    Enforced as structured JSON output from LLM generation routines, representing
    a paired concept prompt and grounded explanatory answer.
    """
    front_text: str = Field(..., description="Question, prompt, key concept, or term")
    back_text: str = Field(..., description="Clear, concise, and accurate answer or definition grounded in the text")
    source_chunk_id: Optional[str] = Field(None, description="UUID of the chunk supporting this flashcard, if provided in context")


class FlashcardSetGenerateSchema(BaseModel):
    """
    Complete Flashcard Deck Generation Schema.

    Enforces structured LLM generation output containing a deck title and collection of cards.
    """
    title: str = Field(..., description="Concise descriptive title for this flashcard deck")
    cards: List[FlashcardItemSchema] = Field(..., description="List of generated flashcards")


class QuizOptionSchema(BaseModel):
    """
    Single Multiple-Choice Quiz Option.

    Represents an individual option choice (A, B, C, or D) with associated text.
    """
    key: str = Field(..., description="Option letter: 'A', 'B', 'C', or 'D'")
    text: str = Field(..., description="Option description text")


class QuizQuestionSchema(BaseModel):
    """
    Single Multiple-Choice Quiz Question.

    Enforces structured LLM generation of a question, multiple choices, the correct key,
    grounded explanation, and source attribution chunk UUID.
    """
    question_text: str = Field(..., description="The multiple choice question")
    options: List[QuizOptionSchema] = Field(..., min_length=2, max_length=6, description="List of selectable options")
    correct_answer: str = Field(..., description="The key of the correct option (e.g. 'A')")
    explanation: Optional[str] = Field(None, description="Explanation grounded in the text explaining why the answer is correct")
    source_chunk_id: Optional[str] = Field(None, description="UUID of the chunk supporting this question, if provided in context")


class QuizGenerateSchema(BaseModel):
    """
    Complete Quiz Generation Schema.

    Enforces structured LLM generation of a full multi-question quiz assessment.
    """
    title: str = Field(..., description="Concise descriptive title for this quiz")
    questions: List[QuizQuestionSchema] = Field(..., description="List of generated quiz questions")


# =========================================================================
# 3. DATABASE & API RESPONSE SCHEMAS
# =========================================================================

class FlashcardResponse(BaseModel):
    """
    Persisted Flashcard Item Response.

    Represents a single flashcard record stored in the database.
    """
    id: UUID
    set_id: UUID
    order_index: int
    front_text: str
    back_text: str
    source_chunk_id: Optional[UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FlashcardSetResponse(BaseModel):
    """
    Persisted Flashcard Deck Response.

    Represents a full flashcard set and its embedded cards.
    """
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
    """
    Persisted Quiz Question Response.

    Represents an individual question in a stored quiz assessment.
    """
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
    """
    Persisted Quiz Assessment Response.

    Represents a full quiz object and its embedded questions.
    """
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


# =========================================================================
# 4. QUIZ ATTEMPT & SUBMISSION EVALUATION SCHEMAS
# =========================================================================

class QuizAttemptSubmit(BaseModel):
    """
    Quiz Submission Payload.

    Maps question IDs to the user's selected choice keys for grading.
    """
    user_answers: Dict[str, str] = Field(..., description="Map of question_id or order_index to selected option key ('A', 'B', etc.)")


class QuestionResult(BaseModel):
    """
    Individual Graded Question Result.

    Provides grading outcome, correct answer reveal, and grounded rationale for a single question.
    """
    question_id: str
    user_answer: Optional[str] = None
    correct_answer: str
    is_correct: bool
    explanation: Optional[str] = None


class QuizAttemptResponse(BaseModel):
    """
    Complete Quiz Evaluation Report.

    Aggregates user score, total questions count, percentage accuracy, and itemized question results.
    """
    score: int
    total_questions: int
    percentage: float
    results: List[QuestionResult]


# =========================================================================
# 5. USER STUDY NOTE SCHEMAS
# =========================================================================

class NoteCreateRequest(BaseModel):
    """
    Note Creation Payload.

    Validates initial title, markdown text content, and optional source chat message link.
    """
    title: Optional[str] = Field("Untitled Note", max_length=255, description="Title of the note")
    content: str = Field(..., description="Markdown or text content of the note")
    source_message_id: Optional[str] = Field(None, description="Optional ID of the chat message this note was saved from")


class NoteUpdateRequest(BaseModel):
    """
    Note Update Payload.

    Supports partial or full updates to note title and markdown body.
    """
    title: Optional[str] = Field(None, max_length=255, description="Updated title of the note")
    content: Optional[str] = Field(None, description="Updated markdown or text content of the note")


class NoteResponse(BaseModel):
    """
    Persisted Study Note Response.

    Represents a user study note stored in the database.
    """
    id: UUID
    notebook_id: UUID
    user_id: UUID
    title: str
    content: str
    source_message_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


