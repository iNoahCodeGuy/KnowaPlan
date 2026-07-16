/* KnowaPlan teaching workspace — reusable retrieval-practice quiz.
 *
 * Markup contract (a lesson writes only HTML, never JS):
 *
 *   <section class="quiz" data-quiz>
 *     <div class="quiz-q" data-answer="dangling">
 *        ...stem markup...
 *        <div class="quiz-choices">
 *          <button data-key="pristine">Nothing charged yet</button>
 *          <button data-key="dangling">Charge outcome unknown</button>
 *        </div>
 *        <div class="quiz-fb" data-key="pristine">Why that's wrong…</div>
 *        <div class="quiz-fb" data-key="dangling">Why that's right…</div>
 *     </div>
 *   </section>
 *
 * Design notes:
 * - Feedback is shown for the CHOSEN key, not just the correct one, so
 *   a wrong answer teaches instead of only scoring.
 * - One shot per question, then locked: this is retrieval practice, not
 *   a guessing game. Guess-until-green builds fluency, not storage.
 * - No dependencies, no build step, works from file://.
 */
(function () {
  "use strict";

  function gradeQuiz(quiz) {
    var questions = quiz.querySelectorAll(".quiz-q");
    var answered = 0, correct = 0;

    var score = document.createElement("p");
    score.className = "quiz-score noprint";
    score.textContent = "0 of " + questions.length + " answered";
    quiz.appendChild(score);

    function refresh() {
      var line = answered + " of " + questions.length + " answered";
      if (answered === questions.length) {
        line += " — " + correct + " right first try";
        line += correct === questions.length
          ? ". Nothing on this page can surprise you now."
          : ". Re-read the ones you missed; that's where the money is.";
      }
      score.textContent = line;
    }

    questions.forEach(function (q) {
      var want = q.getAttribute("data-answer");

      q.querySelectorAll(".quiz-choices button").forEach(function (btn) {
        btn.addEventListener("click", function () {
          if (q.classList.contains("locked")) return;
          q.classList.add("locked");

          var got = btn.getAttribute("data-key");
          var right = got === want;

          btn.classList.add(right ? "correct" : "wrong");
          if (!right) {
            var truth = q.querySelector(
              '.quiz-choices button[data-key="' + want + '"]'
            );
            if (truth) truth.classList.add("correct");
          }

          q.querySelectorAll(".quiz-choices button").forEach(function (b) {
            b.disabled = true;
          });

          var fb = q.querySelector('.quiz-fb[data-key="' + got + '"]');
          if (fb) {
            fb.classList.add("shown", right ? "fb-ok" : "fb-no");
          }

          answered += 1;
          if (right) correct += 1;
          refresh();
        });
      });
    });
  }

  function init() {
    document.querySelectorAll("[data-quiz]").forEach(gradeQuiz);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
