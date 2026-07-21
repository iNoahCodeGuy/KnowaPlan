"""Authoring guard for lesson quizzes — NOT shipped in a lesson.

Checks a lesson's markup against the contract in assets/quiz.js and
the workspace convention that options carry no formatting tells:

  * every .quiz-q's data-answer matches exactly one button data-key
  * every button has a matching .quiz-fb (a wrong answer must teach)
  * no orphan feedback for buttons that don't exist
  * all options in a question have equal word count

That last one is the easy one to break by hand, and it silently
corrupts the data a quiz is supposed to produce: an odd-length
option is a tell, so a right answer stops being evidence of recall.
Found exactly that in three lessons on 2026-07-18, including the
question a learning record was built on.

Usage:  .venv/bin/python assets/check_quiz.py lessons/0007-*.html
        for f in lessons/*.html; do .venv/bin/python assets/check_quiz.py "$f"; done
"""
import re
import sys

src = open(sys.argv[1], encoding="utf-8").read()

# crude but sufficient: split on quiz-q blocks
blocks = re.findall(r'<div class="quiz-q" data-answer="([^"]+)">(.*?)\n</div>', src, re.S)
print(f"questions found: {len(blocks)}")
ok = True
positions = []
for i, (answer, body) in enumerate(blocks, 1):
    btns = re.findall(r'<button data-key="([^"]+)">(.*?)</button>', body, re.S)
    fbs = set(re.findall(r'<div class="quiz-fb" data-key="([^"]+)">', body))
    keys = [k for k, _ in btns]
    words = [len(re.sub(r"<[^>]+>", "", t).split()) for _, t in btns]
    problems = []
    if answer not in keys:
        problems.append(f"data-answer {answer!r} matches no button")
    if len(set(keys)) != len(keys):
        problems.append("duplicate button keys")
    missing_fb = [k for k in keys if k not in fbs]
    if missing_fb:
        problems.append(f"no feedback for {missing_fb}")
    orphan_fb = [k for k in fbs if k not in keys]
    if orphan_fb:
        problems.append(f"feedback for absent buttons {orphan_fb}")
    if len(set(words)) != 1:
        problems.append(f"unequal option word counts {words}")
    if answer in keys:
        positions.append(keys.index(answer) + 1)
    status = "OK " if not problems else "BAD"
    if problems:
        ok = False
    print(f"  Q{i} {status} answer={answer:9} opts={len(btns)} words={words}"
          + ("  <- " + "; ".join(problems) if problems else ""))

# Position bias. Found 2026-07-18: 82% of all questions across the
# workspace had the answer in slot 1, and lessons 3-6 were 100% —
# so slot predicted the answer and a score stopped measuring recall.
# Worse than useless: it can INVERT a score, because a learner who
# notices the run starts avoiding slot 1 on principle.
if len(positions) >= 4:
    top = max(set(positions), key=positions.count)
    share = positions.count(top) / len(positions)
    print(f"  positions {positions} — most common slot {top} "
          f"({share*100:.0f}%)")
    if share > 0.5:
        print(f"  <- POSITION BIAS: slot {top} holds the answer "
              f"{share*100:.0f}% of the time; shuffle the buttons")
        ok = False

print("CONTRACT OK" if ok else "CONTRACT VIOLATIONS")
sys.exit(0 if ok else 1)
