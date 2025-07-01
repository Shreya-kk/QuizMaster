document.addEventListener('DOMContentLoaded', function() {
    if (document.querySelector('.quiz-container')) {
        initQuiz();
    }
});

function initQuiz() {
    let currentQuestionIndex = 0;
    let timerInterval;
    let timeLeft = 15 * 60; // 15 minutes in seconds
    
    // DOM Elements
    const questionTextEl = document.getElementById('question-text');
    const optionsContainerEl = document.getElementById('options-container');
    const questionBubblesEl = document.getElementById('question-bubbles');
    const timeEl = document.getElementById('time');
    const submitBtn = document.getElementById('submit-quiz');
    
    // Start the timer
    startTimer();
    
    // Load the first question
    loadQuestion(currentQuestionIndex);
    
    // Create question bubbles
    createQuestionBubbles();
    
    // Event listeners
    submitBtn.addEventListener('click', submitQuiz);
    
    function startTimer() {
        updateTimerDisplay();
        timerInterval = setInterval(() => {
            timeLeft--;
            updateTimerDisplay();
            
            if (timeLeft <= 0) {
                clearInterval(timerInterval);
                submitQuiz();
            }
        }, 1000);
    }
    
    function updateTimerDisplay() {
        const minutes = Math.floor(timeLeft / 60);
        const seconds = timeLeft % 60;
        timeEl.textContent = `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;
    }
    
    function loadQuestion(index) {
        fetch(`/get_question/${sessionId}/${index}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error(data.error);
                    return;
                }
                
                currentQuestionIndex = index;
                displayQuestion(data.question, data.user_answer);
                updateQuestionBubbles();
            })
            .catch(error => console.error('Error:', error));
    }
    
    function displayQuestion(question, userAnswer) {
        questionTextEl.textContent = question.text;
        optionsContainerEl.innerHTML = '';
        
        question.options.forEach((option, i) => {
            const optionEl = document.createElement('div');
            optionEl.className = 'option';
            if (userAnswer === option) {
                optionEl.classList.add('selected');
            }
            optionEl.textContent = option;
            optionEl.dataset.option = option;
            
            optionEl.addEventListener('click', function() {
                selectOption(option, question.id);
            });
            
            optionsContainerEl.appendChild(optionEl);
        });
    }
    
    function selectOption(option, questionId) {
        // Remove selected class from all options
        document.querySelectorAll('.option').forEach(el => {
            el.classList.remove('selected');
        });
        
        // Add selected class to clicked option
        event.target.classList.add('selected');
        
        // Save the answer
        saveAnswer(questionId, option);
    }
    
    function saveAnswer(questionId, answer) {
        fetch('/submit_answer', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: sessionId,
                question_id: questionId,
                answer: answer
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                updateQuestionBubbles();
            }
        })
        .catch(error => console.error('Error:', error));
    }
    
    function createQuestionBubbles() {
        fetch(`/get_question/${sessionId}/0`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error(data.error);
                    return;
                }
                
                const totalQuestions = data.total_questions;
                questionBubblesEl.innerHTML = '';
                
                for (let i = 0; i < totalQuestions; i++) {
                    const bubble = document.createElement('div');
                    bubble.className = 'question-bubble';
                    bubble.textContent = i + 1;
                    bubble.dataset.index = i;
                    
                    if (i === currentQuestionIndex) {
                        bubble.classList.add('current');
                    }
                    
                    bubble.addEventListener('click', function() {
                        loadQuestion(i);
                    });
                    
                    questionBubblesEl.appendChild(bubble);
                }
                
                updateQuestionBubbles();
            })
            .catch(error => console.error('Error:', error));
    }
    
    function updateQuestionBubbles() {
        fetch(`/get_question/${sessionId}/${currentQuestionIndex}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error(data.error);
                    return;
                }
                
                const bubbles = document.querySelectorAll('.question-bubble');
                bubbles.forEach((bubble, i) => {
                    bubble.classList.remove('current', 'answered');
                    
                    if (i === currentQuestionIndex) {
                        bubble.classList.add('current');
                    }
                    
                    // Check if this question has been answered
                    fetch(`/get_question/${sessionId}/${i}`)
                        .then(response => response.json())
                        .then(qData => {
                            if (qData.user_answer) {
                                bubble.classList.add('answered');
                            }
                        });
                });
            });
    }
    
    function submitQuiz() {
        clearInterval(timerInterval);
        alert('Quiz submitted!');
        // In a real app, you would redirect to a results page
    }
}
