-- ==============================================================================
-- SMALLBOOK COMPLETE DATABASE SCHEMA & SECURITY POLICIES (SUPABASE / POSTGRESQL)
-- ==============================================================================
-- This script idempotently sets up all tables, relations, indexes, helper functions,
-- triggers, Row-Level Security (RLS) policies, and storage bucket permissions required
-- by the SmallBook application.
--
-- Instructions:
-- 1. Open your Supabase Dashboard: https://supabase.com/dashboard/project/<your-project-id>
-- 2. Navigate to "SQL Editor" on the left menu.
-- 3. Click "New query", paste the entire contents of this file, and click "Run".
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. EXTENSIONS
-- ------------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS moddatetime SCHEMA extensions;

-- ------------------------------------------------------------------------------
-- 2. CORE WORKSPACE & SOURCE TABLES
-- ------------------------------------------------------------------------------

-- Notebooks (Workspace containers for research projects)
CREATE TABLE IF NOT EXISTS public.notebooks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    title TEXT NOT NULL DEFAULT 'Untitled SmallBook',
    preferred_llm_provider TEXT DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Sources (Deduplicated document registry)
CREATE TABLE IF NOT EXISTS public.sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE DEFAULT auth.uid(),
    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    page_count INT,
    content_hash TEXT NOT NULL,
    ingestion_status TEXT NOT NULL DEFAULT 'pending',
    ingestion_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT check_storage_path_ownership CHECK (storage_path LIKE (user_id::text || '/%'))
);

-- Notebook Sources (Many-to-many junction enabling cross-notebook sharing)
CREATE TABLE IF NOT EXISTS public.notebook_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID REFERENCES public.notebooks(id) ON DELETE CASCADE,
    source_id UUID REFERENCES public.sources(id) ON DELETE CASCADE,
    linked_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(notebook_id, source_id)
);

-- Ingestion Jobs (Celery background worker task tracking)
CREATE TABLE IF NOT EXISTS public.ingestion_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES public.sources(id) ON DELETE CASCADE,
    celery_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INT DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- Document Chunks (Parent chunks for context resolution)
CREATE TABLE IF NOT EXISTS public.document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES public.sources(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    chunk_index INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id, chunk_index)
);

-- ------------------------------------------------------------------------------
-- 3. CONVERSATIONAL CHAT & CITATION TABLES
-- ------------------------------------------------------------------------------

-- Chat Messages (Hierarchical message tree supporting prompt branching)
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES public.chat_messages(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    llm_provider TEXT,
    llm_model TEXT,
    is_summarized BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Citations (Clickable source citations attached to AI messages)
CREATE TABLE IF NOT EXISTS public.citations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_message_id UUID NOT NULL REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    chunk_id UUID REFERENCES public.document_chunks(id) ON DELETE SET NULL,
    source_title TEXT NOT NULL,
    page_number INT,
    chunk_snapshot TEXT,
    relevance_score REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Conversation State (Rolling summaries and active window tokens)
CREATE TABLE IF NOT EXISTS public.conversation_state (
    notebook_id UUID PRIMARY KEY REFERENCES public.notebooks(id) ON DELETE CASCADE,
    rolling_summary TEXT,
    last_summarized_message_id UUID REFERENCES public.chat_messages(id) ON DELETE SET NULL,
    active_window_token_count INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------------------------
-- 4. BYOK, USER PREFERENCES & QUOTA TABLES
-- ------------------------------------------------------------------------------

-- User LLM Credentials (AES-256-GCM encrypted API key custody)
CREATE TABLE IF NOT EXISTS public.user_llm_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL, -- 'groq', 'google', 'openai', 'anthropic', 'openrouter', 'custom'
    api_key_encrypted TEXT NOT NULL,
    key_last4 TEXT NOT NULL,
    api_base TEXT,
    custom_model_name TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_valid BOOLEAN DEFAULT TRUE,
    last_validated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_user_provider_model UNIQUE (user_id, provider, custom_model_name)
);

-- User LLM Preferences (Selected active models and fallback settings)
CREATE TABLE IF NOT EXISTS public.user_llm_preferences (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    active_model TEXT NOT NULL DEFAULT 'groq/llama-3.3-70b-versatile',
    preferred_models JSONB NOT NULL DEFAULT '[
        {"id": "groq/llama-3.3-70b-versatile", "provider": "groq", "name": "Groq Llama 3.3 70B", "badge": "Fast & Free", "is_free": true},
        {"id": "gemini/gemini-2.0-flash", "provider": "google", "name": "Gemini 2.0 Flash", "badge": "Free", "is_free": true},
        {"id": "gpt-4o", "provider": "openai", "name": "OpenAI GPT-4o", "badge": "Pro", "is_free": false},
        {"id": "claude-3-5-sonnet-20241022", "provider": "anthropic", "name": "Claude 3.5 Sonnet", "badge": "Pro", "is_free": false}
    ]'::jsonb,
    fallback_enabled BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- User Free Tier Usage (Daily query rate limit tracking)
CREATE TABLE IF NOT EXISTS public.user_free_tier_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
    request_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_user_daily_quota UNIQUE (user_id, usage_date)
);

-- ------------------------------------------------------------------------------
-- 5. STUDY STUDIO & NOTES TABLES
-- ------------------------------------------------------------------------------

-- Flashcard Sets
CREATE TABLE IF NOT EXISTS public.flashcard_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    source_id UUID REFERENCES public.sources(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    custom_prompt TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Flashcards
CREATE TABLE IF NOT EXISTS public.flashcards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    set_id UUID NOT NULL REFERENCES public.flashcard_sets(id) ON DELETE CASCADE,
    order_index INT NOT NULL DEFAULT 0,
    front_text TEXT NOT NULL,
    back_text TEXT NOT NULL,
    source_chunk_id UUID REFERENCES public.document_chunks(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Quizzes
CREATE TABLE IF NOT EXISTS public.quizzes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    source_id UUID REFERENCES public.sources(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    custom_prompt TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Quiz Questions
CREATE TABLE IF NOT EXISTS public.quiz_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.quizzes(id) ON DELETE CASCADE,
    order_index INT NOT NULL DEFAULT 0,
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT 'multiple_choice',
    options JSONB NOT NULL,
    correct_answer TEXT NOT NULL,
    explanation TEXT,
    source_chunk_id UUID REFERENCES public.document_chunks(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Quiz Attempts
CREATE TABLE IF NOT EXISTS public.quiz_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES public.quizzes(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    score INT NOT NULL,
    total_questions INT NOT NULL,
    user_answers JSONB NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Workspace Notes
CREATE TABLE IF NOT EXISTS public.notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Untitled Note',
    content TEXT NOT NULL DEFAULT '',
    source_message_id UUID REFERENCES public.chat_messages(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- ------------------------------------------------------------------------------
-- 6. PERFORMANCE & FOREIGN KEY INDEXES
-- ------------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_notebooks_user_id ON public.notebooks(user_id);
CREATE INDEX IF NOT EXISTS idx_sources_user_id ON public.sources(user_id);
CREATE INDEX IF NOT EXISTS idx_notebook_sources_notebook_id ON public.notebook_sources(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notebook_sources_source_id ON public.notebook_sources(source_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_source_id ON public.ingestion_jobs(source_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_source_id ON public.document_chunks(source_id);

CREATE INDEX IF NOT EXISTS idx_chat_messages_notebook_created ON public.chat_messages(notebook_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_parent_id ON public.chat_messages(parent_id);
CREATE INDEX IF NOT EXISTS idx_citations_chat_message_id ON public.citations(chat_message_id);

CREATE INDEX IF NOT EXISTS idx_user_llm_credentials_lookup ON public.user_llm_credentials(user_id, provider, is_active);
CREATE INDEX IF NOT EXISTS idx_user_free_tier_usage_date ON public.user_free_tier_usage(user_id, usage_date);

CREATE INDEX IF NOT EXISTS idx_flashcard_sets_notebook_id ON public.flashcard_sets(notebook_id);
CREATE INDEX IF NOT EXISTS idx_flashcard_sets_user_id ON public.flashcard_sets(user_id);
CREATE INDEX IF NOT EXISTS idx_flashcards_set_id ON public.flashcards(set_id);

CREATE INDEX IF NOT EXISTS idx_quizzes_notebook_id ON public.quizzes(notebook_id);
CREATE INDEX IF NOT EXISTS idx_quizzes_user_id ON public.quizzes(user_id);
CREATE INDEX IF NOT EXISTS idx_quiz_questions_quiz_id ON public.quiz_questions(quiz_id);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_quiz_id ON public.quiz_attempts(quiz_id);

CREATE INDEX IF NOT EXISTS idx_notes_notebook_id ON public.notes(notebook_id);
CREATE INDEX IF NOT EXISTS idx_notes_user_id ON public.notes(user_id);
CREATE INDEX IF NOT EXISTS idx_notes_updated_at ON public.notes(updated_at DESC);

-- ------------------------------------------------------------------------------
-- 7. SECURITY HELPER FUNCTIONS
-- ------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.owns_notebook(target_notebook_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public, pg_temp
AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM public.notebooks 
    WHERE id = target_notebook_id AND user_id = auth.uid()
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.owns_source(target_source_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public, pg_temp
AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM public.sources 
    WHERE id = target_source_id AND user_id = auth.uid()
  );
END;
$$;

-- ------------------------------------------------------------------------------
-- 8. ROW LEVEL SECURITY (RLS) POLICIES
-- ------------------------------------------------------------------------------

-- Enable RLS across all tables
ALTER TABLE public.notebooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notebook_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ingestion_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_llm_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_llm_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_free_tier_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flashcard_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flashcards ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quizzes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notes ENABLE ROW LEVEL SECURITY;

-- Notebooks
DROP POLICY IF EXISTS "Users can manage their own notebooks" ON public.notebooks;
CREATE POLICY "Users can manage their own notebooks"
    ON public.notebooks FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Sources
DROP POLICY IF EXISTS "Users can manage their own sources" ON public.sources;
CREATE POLICY "Users can manage their own sources"
    ON public.sources FOR ALL 
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Notebook Sources
DROP POLICY IF EXISTS "Users can view link" ON public.notebook_sources;
CREATE POLICY "Users can view link"
    ON public.notebook_sources FOR SELECT
    USING (public.owns_notebook(notebook_id) AND public.owns_source(source_id));

DROP POLICY IF EXISTS "Users can create link" ON public.notebook_sources;
CREATE POLICY "Users can create link"
    ON public.notebook_sources FOR INSERT
    WITH CHECK (public.owns_notebook(notebook_id) AND public.owns_source(source_id));

DROP POLICY IF EXISTS "Users can delete link" ON public.notebook_sources;
CREATE POLICY "Users can delete link"
    ON public.notebook_sources FOR DELETE
    USING (public.owns_notebook(notebook_id) AND public.owns_source(source_id));

-- Ingestion Jobs
DROP POLICY IF EXISTS "Users can view their own ingestion jobs" ON public.ingestion_jobs;
CREATE POLICY "Users can view their own ingestion jobs"
    ON public.ingestion_jobs FOR SELECT
    USING (public.owns_source(source_id));

DROP POLICY IF EXISTS "Users can create ingestion jobs" ON public.ingestion_jobs;
CREATE POLICY "Users can create ingestion jobs"
    ON public.ingestion_jobs FOR INSERT
    WITH CHECK (public.owns_source(source_id));

-- Document Chunks
DROP POLICY IF EXISTS "Users can read their own chunks" ON public.document_chunks;
CREATE POLICY "Users can read their own chunks"
    ON public.document_chunks FOR SELECT
    USING (public.owns_source(source_id));

-- Chat Messages
DROP POLICY IF EXISTS "Users can view chat messages" ON public.chat_messages;
CREATE POLICY "Users can view chat messages" 
    ON public.chat_messages FOR SELECT 
    USING (public.owns_notebook(notebook_id));

DROP POLICY IF EXISTS "Users can insert chat messages" ON public.chat_messages;
CREATE POLICY "Users can insert chat messages" 
    ON public.chat_messages FOR INSERT 
    WITH CHECK (public.owns_notebook(notebook_id));

DROP POLICY IF EXISTS "Users can delete chat messages" ON public.chat_messages;
CREATE POLICY "Users can delete chat messages" 
    ON public.chat_messages FOR DELETE 
    USING (public.owns_notebook(notebook_id));

DROP POLICY IF EXISTS "Users can update ONLY their own prompts" ON public.chat_messages;
CREATE POLICY "Users can update ONLY their own prompts" 
    ON public.chat_messages FOR UPDATE 
    USING (public.owns_notebook(notebook_id) AND role = 'user')
    WITH CHECK (public.owns_notebook(notebook_id) AND role = 'user');

-- Citations
DROP POLICY IF EXISTS "Users can view citations for their chat messages" ON public.citations;
CREATE POLICY "Users can view citations for their chat messages" 
    ON public.citations FOR SELECT 
    USING (
        EXISTS (
            SELECT 1 FROM public.chat_messages m
            WHERE m.id = citations.chat_message_id
            AND public.owns_notebook(m.notebook_id)
        )
    );

-- Conversation State
DROP POLICY IF EXISTS "Users can manage conversation state of their notebooks" ON public.conversation_state;
CREATE POLICY "Users can manage conversation state of their notebooks" 
    ON public.conversation_state FOR ALL 
    USING (public.owns_notebook(notebook_id))
    WITH CHECK (public.owns_notebook(notebook_id));

-- BYOK Credentials
DROP POLICY IF EXISTS "user_llm_credentials_select_policy" ON public.user_llm_credentials;
CREATE POLICY "user_llm_credentials_select_policy" 
    ON public.user_llm_credentials FOR SELECT TO authenticated 
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_llm_credentials_insert_policy" ON public.user_llm_credentials;
CREATE POLICY "user_llm_credentials_insert_policy" 
    ON public.user_llm_credentials FOR INSERT TO authenticated 
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_llm_credentials_update_policy" ON public.user_llm_credentials;
CREATE POLICY "user_llm_credentials_update_policy" 
    ON public.user_llm_credentials FOR UPDATE TO authenticated 
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_llm_credentials_delete_policy" ON public.user_llm_credentials;
CREATE POLICY "user_llm_credentials_delete_policy" 
    ON public.user_llm_credentials FOR DELETE TO authenticated 
    USING (auth.uid() = user_id);

-- User Preferences
DROP POLICY IF EXISTS "user_llm_preferences_select_policy" ON public.user_llm_preferences;
CREATE POLICY "user_llm_preferences_select_policy" 
    ON public.user_llm_preferences FOR SELECT TO authenticated 
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_llm_preferences_insert_policy" ON public.user_llm_preferences;
CREATE POLICY "user_llm_preferences_insert_policy" 
    ON public.user_llm_preferences FOR INSERT TO authenticated 
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_llm_preferences_update_policy" ON public.user_llm_preferences;
CREATE POLICY "user_llm_preferences_update_policy" 
    ON public.user_llm_preferences FOR UPDATE TO authenticated 
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_llm_preferences_delete_policy" ON public.user_llm_preferences;
CREATE POLICY "user_llm_preferences_delete_policy" 
    ON public.user_llm_preferences FOR DELETE TO authenticated 
    USING (auth.uid() = user_id);

-- Free Tier Usage
DROP POLICY IF EXISTS "user_free_tier_usage_select_policy" ON public.user_free_tier_usage;
CREATE POLICY "user_free_tier_usage_select_policy" 
    ON public.user_free_tier_usage FOR SELECT TO authenticated 
    USING (auth.uid() = user_id);

-- Flashcard Sets
DROP POLICY IF EXISTS "Users can view their own flashcard sets" ON public.flashcard_sets;
CREATE POLICY "Users can view their own flashcard sets"
    ON public.flashcard_sets FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own flashcard sets" ON public.flashcard_sets;
CREATE POLICY "Users can insert their own flashcard sets"
    ON public.flashcard_sets FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update their own flashcard sets" ON public.flashcard_sets;
CREATE POLICY "Users can update their own flashcard sets"
    ON public.flashcard_sets FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own flashcard sets" ON public.flashcard_sets;
CREATE POLICY "Users can delete their own flashcard sets"
    ON public.flashcard_sets FOR DELETE USING (auth.uid() = user_id);

-- Flashcards
DROP POLICY IF EXISTS "Users can view flashcards belonging to their sets" ON public.flashcards;
CREATE POLICY "Users can view flashcards belonging to their sets"
    ON public.flashcards FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.flashcard_sets s WHERE s.id = flashcards.set_id AND s.user_id = auth.uid()));

DROP POLICY IF EXISTS "Users can insert flashcards into their sets" ON public.flashcards;
CREATE POLICY "Users can insert flashcards into their sets"
    ON public.flashcards FOR INSERT
    WITH CHECK (EXISTS (SELECT 1 FROM public.flashcard_sets s WHERE s.id = flashcards.set_id AND s.user_id = auth.uid()));

DROP POLICY IF EXISTS "Users can delete flashcards from their sets" ON public.flashcards;
CREATE POLICY "Users can delete flashcards from their sets"
    ON public.flashcards FOR DELETE
    USING (EXISTS (SELECT 1 FROM public.flashcard_sets s WHERE s.id = flashcards.set_id AND s.user_id = auth.uid()));

-- Quizzes
DROP POLICY IF EXISTS "Users can view their own quizzes" ON public.quizzes;
CREATE POLICY "Users can view their own quizzes"
    ON public.quizzes FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert their own quizzes" ON public.quizzes;
CREATE POLICY "Users can insert their own quizzes"
    ON public.quizzes FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update their own quizzes" ON public.quizzes;
CREATE POLICY "Users can update their own quizzes"
    ON public.quizzes FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete their own quizzes" ON public.quizzes;
CREATE POLICY "Users can delete their own quizzes"
    ON public.quizzes FOR DELETE USING (auth.uid() = user_id);

-- Quiz Questions
DROP POLICY IF EXISTS "Users can view quiz questions belonging to their quizzes" ON public.quiz_questions;
CREATE POLICY "Users can view quiz questions belonging to their quizzes"
    ON public.quiz_questions FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.quizzes q WHERE q.id = quiz_questions.quiz_id AND q.user_id = auth.uid()));

DROP POLICY IF EXISTS "Users can insert questions into their quizzes" ON public.quiz_questions;
CREATE POLICY "Users can insert questions into their quizzes"
    ON public.quiz_questions FOR INSERT
    WITH CHECK (EXISTS (SELECT 1 FROM public.quizzes q WHERE q.id = quiz_questions.quiz_id AND q.user_id = auth.uid()));

DROP POLICY IF EXISTS "Users can delete questions from their quizzes" ON public.quiz_questions;
CREATE POLICY "Users can delete questions from their quizzes"
    ON public.quiz_questions FOR DELETE
    USING (EXISTS (SELECT 1 FROM public.quizzes q WHERE q.id = quiz_questions.quiz_id AND q.user_id = auth.uid()));

-- Quiz Attempts
DROP POLICY IF EXISTS "Users can view their own quiz attempts" ON public.quiz_attempts;
CREATE POLICY "Users can view their own quiz attempts"
    ON public.quiz_attempts FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can record their own quiz attempts" ON public.quiz_attempts;
CREATE POLICY "Users can record their own quiz attempts"
    ON public.quiz_attempts FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Notes
DROP POLICY IF EXISTS "Users can view notes" ON public.notes;
CREATE POLICY "Users can view notes"
    ON public.notes FOR SELECT USING (public.owns_notebook(notebook_id));

DROP POLICY IF EXISTS "Users can insert notes" ON public.notes;
CREATE POLICY "Users can insert notes"
    ON public.notes FOR INSERT WITH CHECK (public.owns_notebook(notebook_id));

DROP POLICY IF EXISTS "Users can update notes" ON public.notes;
CREATE POLICY "Users can update notes"
    ON public.notes FOR UPDATE USING (public.owns_notebook(notebook_id)) WITH CHECK (public.owns_notebook(notebook_id));

DROP POLICY IF EXISTS "Users can delete notes" ON public.notes;
CREATE POLICY "Users can delete notes"
    ON public.notes FOR DELETE USING (public.owns_notebook(notebook_id));

-- ------------------------------------------------------------------------------
-- 9. SUPABASE STORAGE SETUP & OBJECT RLS
-- ------------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public) 
VALUES ('user-documents', 'user-documents', false)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS "Users can upload to their own folder" ON storage.objects;
CREATE POLICY "Users can upload to their own folder" ON storage.objects
    FOR INSERT WITH CHECK (
        bucket_id = 'user-documents' 
        AND array_length(storage.foldername(name), 1) > 0
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

DROP POLICY IF EXISTS "Users can view their own documents" ON storage.objects;
CREATE POLICY "Users can view their own documents" ON storage.objects
    FOR SELECT USING (
        bucket_id = 'user-documents' 
        AND array_length(storage.foldername(name), 1) > 0
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

DROP POLICY IF EXISTS "Users can update their own documents" ON storage.objects;
CREATE POLICY "Users can update their own documents" ON storage.objects
    FOR UPDATE USING (
        bucket_id = 'user-documents' 
        AND array_length(storage.foldername(name), 1) > 0
        AND (storage.foldername(name))[1] = auth.uid()::text
    ) WITH CHECK (
        bucket_id = 'user-documents' 
        AND array_length(storage.foldername(name), 1) > 0
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

DROP POLICY IF EXISTS "Users can delete their own documents" ON storage.objects;
CREATE POLICY "Users can delete their own documents" ON storage.objects
    FOR DELETE USING (
        bucket_id = 'user-documents' 
        AND array_length(storage.foldername(name), 1) > 0
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

-- ------------------------------------------------------------------------------
-- 10. AUTOMATIC TIMESTAMPTZ TRIGGERS
-- ------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_notebooks_updated_at ON public.notebooks;
CREATE TRIGGER tr_notebooks_updated_at
    BEFORE UPDATE ON public.notebooks
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_conversation_state_updated_at ON public.conversation_state;
CREATE TRIGGER tr_conversation_state_updated_at
    BEFORE UPDATE ON public.conversation_state
    FOR EACH ROW
    EXECUTE FUNCTION moddatetime (updated_at);

DROP TRIGGER IF EXISTS tr_user_llm_credentials_updated_at ON public.user_llm_credentials;
CREATE TRIGGER tr_user_llm_credentials_updated_at
    BEFORE UPDATE ON public.user_llm_credentials
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_user_llm_preferences_updated_at ON public.user_llm_preferences;
CREATE TRIGGER tr_user_llm_preferences_updated_at
    BEFORE UPDATE ON public.user_llm_preferences
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_notes_updated_at ON public.notes;
CREATE TRIGGER tr_notes_updated_at
    BEFORE UPDATE ON public.notes
    FOR EACH ROW
    EXECUTE FUNCTION moddatetime (updated_at);
