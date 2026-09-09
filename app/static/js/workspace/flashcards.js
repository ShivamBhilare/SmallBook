/**
 * SmallBook - Flashcards Player & 3D Flip Viewer
 * Manages interactive study decks, 3D flip card animations,
 * keyboard navigation (Space / Arrow keys), progress tracking, and deck shuffling.
 */
    // ==========================================
    // FLASHCARD VIEWER IN STUDIO (3D FLIP & NAV)
    // ==========================================

    async function openFlashcardInStudio(setId) {
        // 1. Instant render if cached in memory
        if (loadedDecksCache[setId]) {
            const deck = loadedDecksCache[setId];
            currentDeck = deck;
            currentCardIndex = 0;
            isCardFlipped = false;

            openStudioViewer('flashcards', deck.title);
            document.getElementById('studio-fc-container').classList.remove('hidden');
            document.getElementById('studio-quiz-container').classList.add('hidden');

            const cardEl = document.getElementById('studio-flashcard');
            if (cardEl) cardEl.classList.remove('is-flipped');

            updateFlashcardUI();
            return;
        }

        // 2. Immediate feedback on tile icon & loading skeleton in viewer
        const iconContainer = document.getElementById(`card-deck-icon-${setId}`);
        const originalIconHtml = iconContainer ? iconContainer.innerHTML : null;
        if (iconContainer) {
            iconContainer.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>';
        }

        openStudioViewer('flashcards', 'Loading Flashcards...');
        document.getElementById('studio-fc-container').classList.remove('hidden');
        document.getElementById('studio-quiz-container').classList.add('hidden');
        document.getElementById('studio-fc-counter').innerText = 'Loading...';
        document.getElementById('studio-fc-progress').style.width = '20%';
        document.getElementById('studio-fc-front').innerHTML = `
            <div class="flex flex-col items-center justify-center gap-2 py-4">
                <span class="material-symbols-outlined animate-spin text-[24px] text-secondary dark:text-dark-accent">progress_activity</span>
                <span class="text-xs text-on-surface-variant dark:text-dark-text-muted">Opening flashcard deck...</span>
            </div>`;
        document.getElementById('studio-fc-back').innerHTML = '';
        document.getElementById('studio-fc-citation').classList.add('hidden');

        try {
            const res = await fetch(`/api/study/flashcards/${setId}`);
            if (!res.ok) throw new Error('Could not load flashcard deck.');
            const deck = await res.json();

            if (!deck.cards || deck.cards.length === 0) {
                showAppAlert('This deck has no cards.', { title: 'Empty Deck', type: 'info' });
                closeStudioViewer();
                return;
            }

            loadedDecksCache[setId] = deck;
            currentDeck = deck;
            currentCardIndex = 0;
            isCardFlipped = false;

            document.getElementById('studio-viewer-title').innerText = deck.title;
            const cardEl = document.getElementById('studio-flashcard');
            if (cardEl) cardEl.classList.remove('is-flipped');

            updateFlashcardUI();
        } catch (e) {
            console.error(e);
            showAppAlert('Failed to open flashcard deck.', { title: 'Flashcards Error', type: 'error' });
            closeStudioViewer();
        } finally {
            if (iconContainer && originalIconHtml) {
                iconContainer.innerHTML = originalIconHtml;
            }
        }
    }

    function flipFlashcard() {
        const cardEl = document.getElementById('studio-flashcard');
        if (!cardEl) return;
        isCardFlipped = !isCardFlipped;
        if (isCardFlipped) {
            cardEl.classList.add('is-flipped');
        } else {
            cardEl.classList.remove('is-flipped');
        }
    }

    function nextFlashcard() {
        if (!currentDeck || currentCardIndex >= currentDeck.cards.length - 1) return;
        currentCardIndex++;
        isCardFlipped = false;
        const cardEl = document.getElementById('studio-flashcard');
        if (cardEl) cardEl.classList.remove('is-flipped');
        updateFlashcardUI();
    }

    function prevFlashcard() {
        if (!currentDeck || currentCardIndex <= 0) return;
        currentCardIndex--;
        isCardFlipped = false;
        const cardEl = document.getElementById('studio-flashcard');
        if (cardEl) cardEl.classList.remove('is-flipped');
        updateFlashcardUI();
    }

    function shuffleCurrentDeck() {
        if (!currentDeck || !currentDeck.cards) return;
        for (let i = currentDeck.cards.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [currentDeck.cards[i], currentDeck.cards[j]] = [currentDeck.cards[j], currentDeck.cards[i]];
        }
        currentCardIndex = 0;
        isCardFlipped = false;
        const cardEl = document.getElementById('studio-flashcard');
        if (cardEl) cardEl.classList.remove('is-flipped');
        updateFlashcardUI();
    }

    function updateFlashcardUI() {
        if (!currentDeck || !currentDeck.cards) return;
        const total = currentDeck.cards.length;
        const card = currentDeck.cards[currentCardIndex];

        document.getElementById('studio-fc-counter').innerText = `Card ${currentCardIndex + 1} of ${total}`;
        document.getElementById('studio-fc-progress').style.width = `${((currentCardIndex + 1) / total) * 100}%`;

        const fcFront = document.getElementById('studio-fc-front');
        const fcBack = document.getElementById('studio-fc-back');
        if (fcFront) {
            fcFront.innerHTML = formatMarkdownText(card.front_text);
            renderMathSafely(fcFront);
        }
        if (fcBack) {
            fcBack.innerHTML = formatMarkdownText(card.back_text);
            renderMathSafely(fcBack);
        }

        const citationEl = document.getElementById('studio-fc-citation');
        if (card.source_chunk_id) {
            citationEl.innerText = `Source Reference: Chunk ${card.source_chunk_id.substring(0, 8)}...`;
            citationEl.classList.remove('hidden');
        } else {
            citationEl.classList.add('hidden');
        }

        document.getElementById('studio-fc-btn-prev').disabled = currentCardIndex === 0;
        document.getElementById('studio-fc-btn-next').disabled = currentCardIndex === total - 1;
    }

    // Keyboard navigation for Flashcards in Studio
    document.addEventListener('keydown', (e) => {
        const fcContainer = document.getElementById('studio-fc-container');
        if (fcContainer && !fcContainer.classList.contains('hidden')) {
            if (e.code === 'Space') {
                e.preventDefault();
                flipFlashcard();
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                nextFlashcard();
            } else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                prevFlashcard();
            } else if (e.key === 'Escape') {
                closeStudioViewer();
            }
        }
    });

