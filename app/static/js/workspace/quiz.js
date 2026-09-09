/**
 * SmallBook - Quiz Player & Evaluation Controller
 * Handles interactive multiple-choice quizzes, instant option grading,
 * explanation snippets, question navigation, score summaries, and retries.
 */
    // ==========================================
    // QUIZ PLAYER IN STUDIO (MCQs & GRADING)
    // ==========================================

    async function openQuizInStudio(quizId) {
        // 1. Instant render if cached in memory
        if (loadedQuizzesCache[quizId]) {
            const quiz = loadedQuizzesCache[quizId];
            currentQuiz = quiz;
            currentQuizQuestionIndex = 0;
            userQuizAnswers = {};
            isQuizSubmitted = false;

            openStudioViewer('quiz', quiz.title);
            document.getElementById('studio-fc-container').classList.add('hidden');
            document.getElementById('studio-quiz-container').classList.remove('hidden');

            document.getElementById('studio-quiz-question-view').classList.remove('hidden');
            document.getElementById('studio-quiz-results-view').classList.add('hidden');

            updateQuizQuestionUI();
            return;
        }

        // 2. Immediate feedback on tile icon & loading skeleton in viewer
        const iconContainer = document.getElementById(`quiz-item-icon-${quizId}`);
        const originalIconHtml = iconContainer ? iconContainer.innerHTML : null;
        if (iconContainer) {
            iconContainer.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>';
        }

        openStudioViewer('quiz', 'Loading Quiz...');
        document.getElementById('studio-fc-container').classList.add('hidden');
        document.getElementById('studio-quiz-container').classList.remove('hidden');
        document.getElementById('studio-quiz-question-view').classList.remove('hidden');
        document.getElementById('studio-quiz-results-view').classList.add('hidden');
        document.getElementById('studio-quiz-counter').innerText = 'Loading...';
        document.getElementById('studio-quiz-progress').style.width = '20%';
        document.getElementById('studio-quiz-q-text').innerText = 'Loading quiz questions...';
        document.getElementById('studio-quiz-options').innerHTML = `
            <div class="py-6 flex flex-col items-center justify-center gap-2">
                <span class="material-symbols-outlined animate-spin text-[24px] text-green-600 dark:text-green-400">progress_activity</span>
                <span class="text-xs text-on-surface-variant dark:text-dark-text-muted">Fetching quiz...</span>
            </div>`;

        try {
            const res = await fetch(`/api/study/quizzes/${quizId}`);
            if (!res.ok) throw new Error('Could not load quiz.');
            const quiz = await res.json();

            if (!quiz.questions || quiz.questions.length === 0) {
                showAppAlert('This quiz has no questions.', { title: 'Empty Quiz', type: 'info' });
                closeStudioViewer();
                return;
            }

            loadedQuizzesCache[quizId] = quiz;
            currentQuiz = quiz;
            currentQuizQuestionIndex = 0;
            userQuizAnswers = {};
            isQuizSubmitted = false;

            document.getElementById('studio-viewer-title').innerText = quiz.title;
            updateQuizQuestionUI();
        } catch (e) {
            console.error(e);
            showAppAlert('Failed to open quiz player.', { title: 'Quiz Error', type: 'error' });
            closeStudioViewer();
        } finally {
            if (iconContainer && originalIconHtml) {
                iconContainer.innerHTML = originalIconHtml;
            }
        }
    }

    function updateQuizQuestionUI() {
        if (!currentQuiz || !currentQuiz.questions) return;
        const total = currentQuiz.questions.length;
        const q = currentQuiz.questions[currentQuizQuestionIndex];

        document.getElementById('studio-quiz-counter').innerText = `Question ${currentQuizQuestionIndex + 1} of ${total}`;
        document.getElementById('studio-quiz-progress').style.width = `${((currentQuizQuestionIndex + 1) / total) * 100}%`;
        document.getElementById('studio-quiz-q-text').innerText = q.question_text;

        // Render Options
        const container = document.getElementById('studio-quiz-options');
        let optionsHtml = '';
        const currentAnswer = userQuizAnswers[q.id] || userQuizAnswers[currentQuizQuestionIndex] || '';

        q.options.forEach(opt => {
            const isSelected = currentAnswer === opt.key;
            const selectedClasses = isSelected 
                ? 'border-secondary dark:border-dark-accent bg-secondary/10 dark:bg-dark-accent/10 shadow-sm'
                : 'border-paper dark:border-dark-border bg-surface-bright dark:bg-dark-bg hover:border-secondary dark:hover:border-dark-accent';

            optionsHtml += `
                <button type="button" onclick="selectQuizOption('${opt.key}')" class="w-full text-left p-3 rounded-xl border ${selectedClasses} transition-all flex items-start gap-2.5 group">
                    <span class="h-5 w-5 rounded-full border border-secondary/60 dark:border-dark-accent/60 flex items-center justify-center text-[11px] font-bold text-secondary dark:text-dark-accent flex-shrink-0 ${isSelected ? 'bg-secondary dark:bg-dark-accent text-white dark:text-dark-bg' : ''}">
                        ${opt.key}
                    </span>
                    <span class="text-xs text-on-surface dark:text-dark-text leading-relaxed">${escapeHtml(opt.text)}</span>
                </button>
            `;
        });
        container.innerHTML = optionsHtml;

        // Buttons state
        document.getElementById('studio-quiz-btn-prev').disabled = currentQuizQuestionIndex === 0;
        
        const isLastQuestion = currentQuizQuestionIndex === total - 1;
        const btnNext = document.getElementById('studio-quiz-btn-next');
        const btnSubmit = document.getElementById('studio-quiz-btn-submit');

        if (isLastQuestion) {
            btnNext.classList.add('hidden');
            btnSubmit.classList.remove('hidden');
        } else {
            btnNext.classList.remove('hidden');
            btnSubmit.classList.add('hidden');
        }
    }

    function selectQuizOption(optKey) {
        if (!currentQuiz || isQuizSubmitted) return;
        const q = currentQuiz.questions[currentQuizQuestionIndex];
        userQuizAnswers[q.id] = optKey;
        userQuizAnswers[currentQuizQuestionIndex] = optKey;
        updateQuizQuestionUI();
    }

    function nextQuizQuestion() {
        if (!currentQuiz || currentQuizQuestionIndex >= currentQuiz.questions.length - 1) return;
        currentQuizQuestionIndex++;
        updateQuizQuestionUI();
    }

    function prevQuizQuestion() {
        if (!currentQuiz || currentQuizQuestionIndex <= 0) return;
        currentQuizQuestionIndex--;
        updateQuizQuestionUI();
    }

    async function submitQuiz() {
        if (!currentQuiz || isQuizSubmitted) return;

        try {
            const res = await fetch(`/api/study/quizzes/${currentQuiz.id}/submit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_answers: userQuizAnswers })
            });

            if (!res.ok) throw new Error('Failed to grade quiz.');
            const gradeResult = await res.json();
            
            isQuizSubmitted = true;
            renderQuizResults(gradeResult);
        } catch (err) {
            showAppAlert(err.message || 'Error grading quiz attempt.', { title: 'Grading Error', type: 'error' });
        }
    }

    function renderQuizResults(result) {
        document.getElementById('studio-quiz-question-view').classList.add('hidden');
        document.getElementById('studio-quiz-results-view').classList.remove('hidden');

        document.getElementById('studio-quiz-score-percent').innerText = `${result.percentage}%`;
        document.getElementById('studio-quiz-score-detail').innerText = `You scored ${result.score} out of ${result.total_questions} questions correctly.`;

        const listEl = document.getElementById('studio-quiz-review-list');
        let html = '';

        currentQuiz.questions.forEach((q, idx) => {
            const userAns = userQuizAnswers[q.id] || userQuizAnswers[idx] || 'None';
            const correctAns = q.correct_answer;
            const isCorrect = userAns === correctAns;

            html += `
                <div class="p-3 rounded-xl border ${isCorrect ? 'border-green-500/40 bg-green-500/5' : 'border-error/40 bg-error/5'} space-y-1.5">
                    <div class="flex items-center justify-between text-[11px] font-semibold">
                        <span class="text-on-surface dark:text-dark-text truncate pr-2">Q${idx + 1}: ${escapeHtml(q.question_text)}</span>
                        <span class="px-2 py-0.5 rounded-full text-[10px] flex-shrink-0 ${isCorrect ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400' : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400'}">
                            ${isCorrect ? 'Correct' : 'Incorrect'}
                        </span>
                    </div>
                    <div class="text-[11px] text-on-surface-variant dark:text-dark-text-muted space-y-1">
                        <div>Your: <span class="font-semibold ${isCorrect ? 'text-green-600 dark:text-green-400' : 'text-error dark:text-red-400'}">${userAns}</span> | Correct: <span class="font-semibold text-green-600 dark:text-green-400">${correctAns}</span></div>
                        ${q.explanation ? `<div class="p-2 rounded-lg bg-surface-bright dark:bg-dark-bg border border-paper dark:border-dark-border text-[10px] leading-relaxed"><span class="font-semibold">Explanation:</span> ${escapeHtml(q.explanation)}</div>` : ''}
                    </div>
                </div>`;
        });

        listEl.innerHTML = html;
    }

    function retakeCurrentQuiz() {
        if (!currentQuiz) return;
        currentQuizQuestionIndex = 0;
        userQuizAnswers = {};
        isQuizSubmitted = false;

        document.getElementById('studio-quiz-question-view').classList.remove('hidden');
        document.getElementById('studio-quiz-results-view').classList.add('hidden');

        updateQuizQuestionUI();
    }

